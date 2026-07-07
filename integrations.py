import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


BACKEND_DIR = Path(__file__).resolve().parent


def load_env():
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def integration_status():
    load_env()
    source_type = os.environ.get("EXTERNAL_SOURCE_TYPE", "none").lower()
    return {
        "external_source": {
            "type": source_type,
            "configured": source_type != "none",
            "api_base": bool(os.environ.get("EXTERNAL_API_BASE") or os.environ.get("EXTERNAL_API_RECORDS_URL")),
            "sqlite_path": os.environ.get("EXTERNAL_SQLITE_PATH", ""),
            "postgres_url": bool(os.environ.get("EXTERNAL_POSTGRES_URL") or os.environ.get("EXTERNAL_DATABASE_URL")),
        },
        "ai": {
            "provider": os.environ.get("AI_PROVIDER", "openai-compatible"),
            "configured": bool(os.environ.get("AI_API_KEY")),
            "api_base": os.environ.get("AI_API_BASE", "https://api.deepseek.com"),
            "model": os.environ.get("AI_MODEL", ""),
            "fallback": "local-rule",
        },
    }


def http_json(url, token="", method="GET", payload=None, timeout=20):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def normalize_record(item, default_source="外部系统"):
    if not isinstance(item, dict):
        return None
    text = (
        item.get("text")
        or item.get("content")
        or item.get("note")
        or item.get("description")
        or item.get("value")
        or ""
    )
    text = str(text).strip()
    if not text:
        return None
    return {
        "type": str(item.get("type") or item.get("tag") or "外部记录"),
        "source": str(item.get("source") or item.get("system") or default_source),
        "time": str(item.get("time") or item.get("time_label") or item.get("created_at") or item.get("date") or ""),
        "text": text,
        "confidence": str(item.get("confidence") or "中"),
    }


def records_from_api(elder_id):
    base = os.environ.get("EXTERNAL_API_BASE", "").rstrip("/")
    records_url = os.environ.get("EXTERNAL_API_RECORDS_URL", "").strip()
    token = os.environ.get("EXTERNAL_API_TOKEN", "")
    if records_url:
        url = records_url.replace("{elder_id}", quote(elder_id))
    elif base:
        query = urlencode({"elder_id": elder_id})
        url = f"{base}/records?{query}"
    else:
        return []
    data = http_json(url, token=token)
    raw_records = data.get("records") or data.get("data") or data
    if isinstance(raw_records, dict):
        raw_records = raw_records.get("items") or []
    return [record for record in (normalize_record(item) for item in raw_records) if record]


def records_from_sqlite(elder_id):
    sqlite_path = os.environ.get("EXTERNAL_SQLITE_PATH", "").strip()
    if not sqlite_path:
        return []
    query = os.environ.get(
        "EXTERNAL_SQLITE_QUERY",
        "SELECT type, source, time_label AS time, text, confidence FROM care_records WHERE elder_id = ? LIMIT 50",
    )
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, (elder_id,)).fetchall()
    return [record for record in (normalize_record(dict(row), "外部SQLite") for row in rows) if record]


def records_from_postgres(elder_id):
    if psycopg is None:
        raise RuntimeError("Missing psycopg. Run: pip install -r backend/requirements.txt")
    postgres_url = os.environ.get("EXTERNAL_POSTGRES_URL") or os.environ.get("EXTERNAL_DATABASE_URL", "")
    postgres_url = postgres_url.strip()
    if not postgres_url:
        return []
    query = os.environ.get(
        "EXTERNAL_POSTGRES_QUERY",
        """
        SELECT type, source, time_label AS time, text, confidence
        FROM care_records
        WHERE elder_id = %s
        ORDER BY time_label DESC
        LIMIT 50
        """,
    )
    with psycopg.connect(postgres_url, row_factory=dict_row) as conn:
        rows = conn.execute(query, (elder_id,)).fetchall()
    return [record for record in (normalize_record(dict(row), "外部Postgres") for row in rows) if record]


def fetch_external_records(elder_id):
    load_env()
    source_type = os.environ.get("EXTERNAL_SOURCE_TYPE", "none").lower()
    if source_type in ("", "none", "local"):
        return []
    if source_type == "api":
        return records_from_api(elder_id)
    if source_type == "sqlite":
        return records_from_sqlite(elder_id)
    if source_type in ("postgres", "postgresql", "neon"):
        return records_from_postgres(elder_id)
    raise ValueError(f"暂不支持的外部数据源: {source_type}")


def redact_sensitive_text(value):
    text = str(value)
    text = re.sub(r"1[3-9]\d{9}", "手机号已脱敏", text)
    text = re.sub(r"\b\d{17}[\dXx]\b", "身份证已脱敏", text)
    return text


def redact_context(context):
    def walk(value):
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            return redact_sensitive_text(value)
        return value

    return walk(context)


def local_profile(context):
    elder = context["elder"]
    tasks = context.get("tasks", [])
    records = context.get("external_records", [])
    observations = elder.get("observations", [])
    risk_tags = []
    for task in tasks:
        risk_tags.extend(task.get("risks", []))
    risk_tags = list(dict.fromkeys(risk_tags))[:6]
    evidence = []
    for item in (records + observations)[:5]:
        evidence.append(
            {
                "source": item.get("source") or item.get("tag") or "记录",
                "time": item.get("time", ""),
                "text": item.get("text", ""),
                "confidence": item.get("confidence", "中"),
            }
        )
    summary = f"{elder['name']}，{elder.get('status', '')}。重点看：{elder.get('mobility', '')}。"
    return {
        "profile": {
            "elder_id": elder["id"],
            "name": elder["name"],
            "summary": summary,
            "risk_tags": risk_tags,
            "preference_tags": elder.get("preferenceTags", [])[:6],
            "avoid_tags": elder.get("avoidTags", [])[:6],
            "communication_tips": elder.get("familySummary", [])[:4],
            "care_focus": [task.get("mainAction", "") for task in tasks[:3] if task.get("mainAction")],
            "evidence": evidence,
            "confidence": "中",
            "next_actions": [
                {
                    "title": task.get("actionTitle", task.get("title", "")),
                    "action": task.get("mainAction", ""),
                    "safety": task.get("safetyText", ""),
                }
                for task in tasks[:3]
            ],
        },
        "generated_by": "local-rule",
        "model": "local-rule",
        "raw": "",
    }


def local_daily_summary(context):
    elders = context.get("elders", {})
    tasks = context.get("tasks", [])
    feedback = context.get("feedback", [])
    family_inputs = context.get("family_inputs", [])
    story_cards = []
    care_experiences = []
    task_suggestions = []
    pending_confirmations = []

    for elder_id, elder in elders.items():
        observations = elder.get("observations", [])
        first_family = elder.get("familySummary", ["先尊重老人习惯，再开始照护。"])[0]
        preference = "、".join(elder.get("preferenceTags", [])[:3]) or "熟悉的人和物"
        avoid = elder.get("avoidTags", ["不要催促"])[0]
        story_cards.append(
            {
                "elder_id": elder_id,
                "section": "生活习惯",
                "title": f"{elder['name']}的安抚线索",
                "content": f"{elder['name']}对{preference}更熟悉，照护前先给出熟悉线索。",
                "care_meaning": f"开始任务前先提醒：{first_family}",
                "confidence": "中",
                "status": "active",
                "evidence": [
                    {
                        "source_type": "家属摘要",
                        "source": elder.get("contact", "家属"),
                        "time": "建档",
                        "text": first_family,
                        "confidence": "中",
                    }
                ],
            }
        )
        if observations:
            item = observations[0]
            story_cards.append(
                {
                    "elder_id": elder_id,
                    "section": "近期变化",
                    "title": item.get("title", "近期观察"),
                    "content": item.get("text", ""),
                    "care_meaning": "后续任务先观察当天状态，不硬推。",
                    "confidence": "中",
                    "status": "active",
                    "evidence": [
                        {
                            "source_type": item.get("tag", "观察"),
                            "source": item.get("tag", "记录"),
                            "time": item.get("time", ""),
                            "text": item.get("text", ""),
                            "confidence": "中",
                        }
                    ],
                }
            )
        care_experiences.append(
            {
                "elder_id": elder_id,
                "task_type": "通用照护",
                "method": f"先顺着{preference}切入，再开始任务。",
                "why_it_works": first_family,
                "source": "家属摘要",
                "confidence": "中",
                "safety": "只做沟通安抚；医疗、急救、约束按机构流程。",
                "status": "active",
            }
        )
        if avoid:
            pending_confirmations.append(
                {
                    "elder_id": elder_id,
                    "title": f"确认禁忌：{avoid}",
                    "content": f"系统识别到“{avoid}”可能影响照护配合度，建议家属或管理员确认。",
                    "suggested_value": avoid,
                    "source": "本地规则",
                    "confidence": "低",
                    "status": "pending",
                }
            )

    for task in tasks:
        elder = elders.get(task.get("elderId"))
        if not elder:
            continue
        safety = task.get("safetyText", "异常就停，按机构流程。")
        if task.get("safetyLevel") == "high":
            safety = "高风险。先人工确认，遵循机构流程。"
        task_suggestions.append(
            {
                "task_id": task["id"],
                "elder_id": task["elderId"],
                "headline": task.get("actionTitle") or task.get("title", ""),
                "action": task.get("mainAction", ""),
                "script": task.get("script", ""),
                "safety": safety,
                "source_summary": task.get("confidenceNote") or "来自现有任务证据和老人画像。",
                "confidence": task.get("confidence", 60),
                "evidence": task.get("evidence", [])[:3],
            }
        )

    for item in family_inputs:
        elder_id = item.get("elder_id")
        elder = elders.get(elder_id)
        if not elder:
            continue
        text = item.get("content", "")
        story_cards.append(
            {
                "elder_id": elder_id,
                "section": "家属补充",
                "title": "家属补充的小故事",
                "content": text,
                "care_meaning": "下次照护前可先用家属补充的熟悉线索建立信任。",
                "confidence": "中",
                "status": "active",
                "evidence": [
                    {
                        "source_type": "家属输入",
                        "source": item.get("author", "家属"),
                        "time": item.get("created_at", ""),
                        "text": text,
                        "confidence": "中",
                    }
                ],
            }
        )

    return {
        "summary": {
            "story_cards": story_cards[:12],
            "care_experiences": care_experiences[:12],
            "task_suggestions": task_suggestions[:20],
            "pending_confirmations": pending_confirmations[:8],
        },
        "generated_by": "local-rule",
        "model": "local-rule",
        "warning": "",
        "raw": "",
    }


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def call_ai_profile(context):
    load_env()
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        result = local_profile(context)
        result["warning"] = "未配置 AI_API_KEY，已使用本地规则生成。"
        return result

    api_base = os.environ.get("AI_API_BASE", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("AI_MODEL", "")
    if not model:
        result = local_profile(context)
        result["warning"] = "未配置 AI_MODEL，已使用本地规则生成。"
        return result

    safe_context = redact_context(context)
    messages = [
        {
            "role": "system",
            "content": (
                "你是养老照护画像分析助手。只输出 JSON，不要 Markdown。"
                "内容必须适合护理员快速执行，不替代医疗判断。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "任务": "根据老人资料、观察、反馈和外部记录生成照护画像。",
                    "输出格式": {
                        "profile": {
                            "elder_id": "string",
                            "name": "string",
                            "summary": "一句话画像",
                            "risk_tags": ["风险标签"],
                            "preference_tags": ["偏好"],
                            "avoid_tags": ["禁忌"],
                            "communication_tips": ["护理员话术提示"],
                            "care_focus": ["近期照护重点"],
                            "evidence": [
                                {"source": "来源", "time": "时间", "text": "依据", "confidence": "高/中/低"}
                            ],
                            "confidence": "高/中/低",
                            "next_actions": [
                                {"title": "行动名", "action": "怎么做", "safety": "安全边界"}
                            ],
                        }
                    },
                    "数据": safe_context,
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    data = http_json(f"{api_base}/chat/completions", token=api_key, method="POST", payload=payload, timeout=60)
    content = data["choices"][0]["message"]["content"]
    parsed = extract_json(content)
    if "profile" not in parsed:
        parsed = {"profile": parsed}
    return {"profile": parsed["profile"], "generated_by": "ai", "model": model, "raw": content}


def generate_care_profile(context):
    try:
        return call_ai_profile(context)
    except Exception as exc:
        result = local_profile(context)
        result["warning"] = f"AI 调用失败，已使用本地规则生成: {exc}"
        return result


def call_ai_daily_summary(context):
    load_env()
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        result = local_daily_summary(context)
        result["warning"] = "未配置 AI_API_KEY，已使用本地规则生成每日汇总。"
        return result

    api_base = os.environ.get("AI_API_BASE", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("AI_MODEL", "")
    if not model:
        result = local_daily_summary(context)
        result["warning"] = "未配置 AI_MODEL，已使用本地规则生成每日汇总。"
        return result

    safe_context = redact_context(context)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 CareAction 的养老照护信息整理员。你的任务是把已有老人认知、家属输入、"
                "护理记录和有效经验整理成可执行照护建议。只输出 JSON，不要 Markdown。"
                "边界：不做医疗诊断，不给用药建议，不替代急救、约束、跌倒、吞咽等机构流程。"
                "没有证据时不要编造偏好；低置信或冲突内容必须放入 pending_confirmations。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "任务": "生成每日汇总，用于人生故事书、有效照护经验库和当前任务大卡片。",
                    "输出格式": {
                        "summary": {
                            "story_cards": [
                                {
                                    "elder_id": "string",
                                    "section": "人生经历/重要关系/生活习惯/喜欢的事/害怕禁忌/近期变化/照护要点",
                                    "title": "string",
                                    "content": "给家属和管理端看的故事卡内容",
                                    "care_meaning": "转化成照护行动的含义",
                                    "confidence": "高/中/低",
                                    "status": "active",
                                    "evidence": [
                                        {
                                            "source_type": "家属输入/护理记录/观察/经验",
                                            "source": "string",
                                            "time": "string",
                                            "text": "证据摘要",
                                            "confidence": "高/中/低",
                                        }
                                    ],
                                }
                            ],
                            "care_experiences": [
                                {
                                    "elder_id": "string",
                                    "task_type": "吃饭/洗漱/转移/活动/沟通/通用照护",
                                    "method": "可复用的好方法",
                                    "why_it_works": "为什么有效",
                                    "source": "来源",
                                    "confidence": "高/中/低",
                                    "safety": "安全边界",
                                    "status": "active",
                                }
                            ],
                            "task_suggestions": [
                                {
                                    "task_id": "string",
                                    "elder_id": "string",
                                    "headline": "一句话建议",
                                    "action": "护工现在怎么做",
                                    "script": "护工可以照着说的话",
                                    "safety": "最关键注意事项",
                                    "source_summary": "依据摘要",
                                    "confidence": 0,
                                    "evidence": [{"source": "string", "time": "string", "text": "string", "confidence": "高/中/低"}],
                                }
                            ],
                            "pending_confirmations": [
                                {
                                    "elder_id": "string",
                                    "title": "待确认标题",
                                    "content": "为什么需要确认",
                                    "suggested_value": "建议写入内容",
                                    "source": "来源",
                                    "confidence": "低",
                                    "status": "pending",
                                }
                            ],
                        }
                    },
                    "数据": safe_context,
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    data = http_json(f"{api_base}/chat/completions", token=api_key, method="POST", payload=payload, timeout=90)
    content = data["choices"][0]["message"]["content"]
    parsed = extract_json(content)
    if "summary" not in parsed:
        parsed = {"summary": parsed}
    return {"summary": parsed["summary"], "generated_by": "ai", "model": model, "raw": content}


def generate_daily_summary(context):
    try:
        return call_ai_daily_summary(context)
    except Exception as exc:
        result = local_daily_summary(context)
        result["warning"] = f"AI 调用失败，已使用本地规则生成每日汇总: {exc}"
        return result
