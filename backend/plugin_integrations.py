import json
import os

from integrations import extract_json, http_json, load_env, redact_context


def _first_clean(items, fallback=""):
    if isinstance(items, list):
        for item in items:
            text = str(item or "").strip()
            if text:
                return text
    text = str(items or "").strip()
    return text or fallback


def _clamp_confidence(value, fallback=60):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = fallback
    return max(0, min(100, number))


def _task_is_high_risk(task):
    text = " ".join(
        [
            str(task.get("title", "")),
            str(task.get("priority", "")),
            str(task.get("safetyLevel", "")),
            str(task.get("safetyTitle", "")),
            str(task.get("safetyText", "")),
            " ".join(str(item) for item in task.get("risks", []) if item),
        ]
    )
    keywords = ["高", "吞咽", "跌倒", "转移", "用药", "急救", "约束", "咳嗽", "湿哑", "发热", "出血"]
    return any(keyword in text for keyword in keywords)


def _plugin_evidence(context):
    evidence = []
    task = context.get("task", {})
    for item in task.get("evidence", [])[:3]:
        if isinstance(item, dict):
            evidence.append(
                {
                    "source": str(item.get("source") or item.get("type") or "任务依据"),
                    "time": str(item.get("time") or ""),
                    "text": str(item.get("text") or ""),
                    "confidence": str(item.get("confidence") or ""),
                }
            )
    for card in context.get("life_story_cards", [])[:2]:
        evidence.append(
            {
                "source": str(card.get("title") or card.get("section") or "人生故事书"),
                "time": str(card.get("created_at") or ""),
                "text": str(card.get("care_meaning") or card.get("content") or ""),
                "confidence": str(card.get("confidence") or ""),
            }
        )
    for item in context.get("care_experiences", [])[:2]:
        evidence.append(
            {
                "source": str(item.get("source") or "有效照护经验"),
                "time": str(item.get("created_at") or ""),
                "text": str(item.get("method") or ""),
                "confidence": str(item.get("confidence") or ""),
            }
        )
    for item in context.get("raw_inputs", [])[:2]:
        evidence.append(
            {
                "source": str(item.get("source_name") or item.get("source_type") or "原始资料"),
                "time": str(item.get("occurred_at") or item.get("created_at") or ""),
                "text": str(item.get("content") or "")[:120],
                "confidence": str(item.get("confidence") or ""),
            }
        )
    return [item for item in evidence if item.get("text")][:6]


def local_plugin_suggestion(context):
    task = context.get("task", {})
    elder = context.get("elder", {})
    experiences = context.get("care_experiences", [])
    steps = [str(item).strip() for item in task.get("steps", []) if str(item).strip()]
    method = _first_clean([item.get("method") for item in experiences if isinstance(item, dict)], "")
    if method and method not in steps:
        steps.insert(0, method)
    if not steps:
        steps = [
            str(task.get("mainAction") or task.get("actionTitle") or task.get("title") or "先确认老人状态，再开始照护。")
        ]
    script = str(task.get("script") or "").strip()
    if not script:
        name = elder.get("name") or "老人"
        script = f"{name}，我先跟您说一下，现在开始做这件事，我们慢慢来。"
    if _task_is_high_risk(task):
        safety = "高风险事项：先人工确认，遵循机构流程，必要时通知护士/医生。AI 不替代专业医疗判断。"
    else:
        safety = str(task.get("safetyText") or "如老人不适或拒绝，先停下并按机构流程处理。")
    headline = str(task.get("actionTitle") or task.get("mainAction") or task.get("title") or "按老人习惯完成当前任务")
    return {
        "suggestion": {
            "task_id": task.get("id", ""),
            "elder_id": elder.get("id") or task.get("elderId", ""),
            "headline": headline,
            "steps": steps[:3],
            "script": script,
            "safety": safety,
            "source_summary": str(task.get("confidenceNote") or "来自老人画像、护理记录和有效照护经验。"),
            "confidence": _clamp_confidence(task.get("confidence"), 60),
            "evidence": _plugin_evidence(context),
        },
        "generated_by": "local-rule",
        "model": "local-rule",
        "warning": "",
        "raw": "",
    }


def call_ai_plugin_suggestion(context):
    load_env()
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        result = local_plugin_suggestion(context)
        result["warning"] = "未配置 AI_API_KEY，已使用本地规则生成。"
        return result

    api_base = os.environ.get("AI_API_BASE", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("AI_MODEL", "")
    if not model:
        result = local_plugin_suggestion(context)
        result["warning"] = "未配置 AI_MODEL，已使用本地规则生成。"
        return result

    safe_context = redact_context(context)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 CareAction 嵌入式护工软件插件。你的任务是把已有老人资料、机构任务、照护经验和记录，"
                "转成护工现场能立刻执行的个性化照护建议。只输出 JSON，不要 Markdown。"
                "必须基于证据，不得编造老人偏好。不得做医疗诊断、用药建议、急救处理、约束处理、跌倒或吞咽异常结论。"
                "遇到高风险或证据不足，必须提示遵循机构流程、人工确认、通知护士/医生。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "任务": "为当前护理任务生成嵌入式插件建议。",
                    "输出格式": {
                        "suggestion": {
                            "headline": "一句话行动建议",
                            "steps": ["先做什么", "再做什么", "最后确认什么"],
                            "script": "护工可直接照着说的一句话",
                            "safety": "最关键安全提醒",
                            "source_summary": "依据摘要",
                            "confidence": 0,
                            "evidence": [
                                {"source": "来源", "time": "时间", "text": "依据", "confidence": "高/中/低"}
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
    if "suggestion" not in parsed:
        parsed = {"suggestion": parsed}
    suggestion = parsed["suggestion"]
    if _task_is_high_risk(context.get("task", {})):
        safety = str(suggestion.get("safety") or "")
        boundary = "遵循机构流程 / 人工确认 / 通知护士医生"
        if boundary not in safety:
            suggestion["safety"] = f"{safety} {boundary}".strip()
    suggestion["confidence"] = _clamp_confidence(suggestion.get("confidence"), context.get("task", {}).get("confidence", 60))
    suggestion["evidence"] = suggestion.get("evidence") or _plugin_evidence(context)
    return {"suggestion": suggestion, "generated_by": "ai", "model": model, "raw": content}


def generate_plugin_suggestion(context):
    try:
        return call_ai_plugin_suggestion(context)
    except Exception as exc:
        result = local_plugin_suggestion(context)
        result["warning"] = f"AI 调用失败，已使用本地规则生成: {exc}"
        return result
