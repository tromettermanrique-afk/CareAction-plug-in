import json
import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import server
from integrations import fetch_external_records, http_json, integration_status, load_env


def mask(value):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:6]}...{text[-4:]}"


def main():
    load_env()
    report = {"checks": []}

    try:
        server.init_db()
        with server.connect() as conn:
            elders = server.get_elders(conn)
        report["checks"].append({"name": "CareAction database", "ok": True, "detail": f"{len(elders)} elders loaded"})
    except Exception as exc:
        report["checks"].append({"name": "CareAction database", "ok": False, "detail": str(exc)})

    try:
        status = integration_status()
        report["integration_status"] = status
        source_type = status["external_source"]["type"]
        if source_type in ("", "none", "local"):
            report["checks"].append({"name": "External source", "ok": True, "detail": "not configured"})
        else:
            records = fetch_external_records(os.environ.get("CHECK_ELDER_ID", "zhou"))
            report["checks"].append({"name": "External source", "ok": True, "detail": f"{len(records)} records fetched"})
    except Exception as exc:
        report["checks"].append({"name": "External source", "ok": False, "detail": str(exc)})

    try:
        api_key = os.environ.get("AI_API_KEY", "")
        api_base = os.environ.get("AI_API_BASE", "https://api.deepseek.com").rstrip("/")
        model = os.environ.get("AI_MODEL", "")
        if not api_key or not model:
            report["checks"].append({"name": "AI API", "ok": True, "detail": "not configured; local fallback will be used"})
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "只输出 OK。"},
                    {"role": "user", "content": "连接测试"},
                ],
                "temperature": 0,
                "max_tokens": 8,
            }
            data = http_json(f"{api_base}/chat/completions", token=api_key, method="POST", payload=payload, timeout=20)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            report["checks"].append({"name": "AI API", "ok": True, "detail": f"model={model}, response={content[:30]}"})
        report["ai"] = {"api_base": api_base, "model": model, "key": mask(api_key)}
    except Exception as exc:
        report["checks"].append({"name": "AI API", "ok": False, "detail": str(exc)})

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(not item["ok"] for item in report["checks"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
