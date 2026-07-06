from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import sqlite3

from integrations import fetch_external_records, generate_care_profile, integration_status, load_env

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(__file__).resolve().parent / "careaction.sqlite3"
load_env()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
PORT = int(os.environ.get("PORT") or os.environ.get("CAREACTION_PORT", "3000"))


SEED_ELDERS = [
    {
        "id": "zhou",
        "name": "周雅琴",
        "initial": "周",
        "age": 82,
        "room": "302",
        "status": "轻中度认知障碍",
        "contact": "女儿 周敏",
        "mobility": "可扶行，晨间需看护",
        "diet": "软食，偏好温热饮",
        "preferenceTags": ["红围巾", "沪剧", "女儿来", "温水"],
        "avoidTags": ["别否定", "别催", "不谈搬家", "避强光"],
        "familySummary": ["红围巾能安抚。", "说“女儿等会儿来”有用。", "不要说她记错。"],
        "observations": [
            {"time": "今天 07:48", "title": "找红围巾", "text": "反复找围巾，有点急。", "tag": "观察"},
            {"time": "昨天", "title": "女儿线索有效", "text": "提到女儿会来，情绪变稳。", "tag": "反馈"},
            {"time": "07-03", "title": "先围巾再洗脸", "text": "先整理围巾后愿意洗漱。", "tag": "反馈"},
        ],
    },
    {
        "id": "liu",
        "name": "刘建国",
        "initial": "刘",
        "age": 76,
        "room": "218",
        "status": "轻度吞咽风险",
        "contact": "儿子 刘洋",
        "mobility": "可独立坐起，午后易疲劳",
        "diet": "半流质，需小口慢食",
        "preferenceTags": ["沪剧", "热粥", "刘老师", "慢慢吃"],
        "avoidTags": ["别催吃", "别冷粥", "不聊复杂事", "问护士"],
        "familySummary": ["叫“刘老师”更愿意回应。", "饭前听沪剧有帮助。", "吞咽不顺就停，叫护士。"],
        "observations": [
            {"time": "今天", "title": "吃得慢", "text": "喝粥停顿多，未呛咳。", "tag": "观察"},
            {"time": "昨天", "title": "沪剧有用", "text": "听沪剧后愿意继续吃。", "tag": "反馈"},
            {"time": "07-02", "title": "粥要热", "text": "冷粥会拒绝。", "tag": "家属"},
        ],
    },
    {
        "id": "chen",
        "name": "陈淑芬",
        "initial": "陈",
        "age": 88,
        "room": "115",
        "status": "跌倒高风险",
        "contact": "孙女 林可",
        "mobility": "夜间起身需陪同",
        "diet": "清淡软食",
        "preferenceTags": ["靠窗", "蓝外套", "先说明", "慢慢来"],
        "avoidTags": ["别独自下床", "防滑", "别突然扶", "需确认"],
        "familySummary": ["先说明，再扶。", "夜里起身多，防跌倒。", "转移不稳，按流程。"],
        "observations": [
            {"time": "今天", "title": "夜里起身", "text": "床边报警两次。", "tag": "设备"},
            {"time": "昨天", "title": "先说明有用", "text": "说明后愿意起身。", "tag": "反馈"},
            {"time": "07-01", "title": "脚踝不适", "text": "已建议护士看。", "tag": "确认"},
        ],
    },
]


SEED_TASKS = [
    {
        "id": "t1",
        "elderId": "zhou",
        "time": "08:30",
        "title": "洗漱协助",
        "status": "待执行",
        "priority": "高优先",
        "risks": ["焦虑", "重复询问"],
        "confidence": 78,
        "confidenceLabel": "中高",
        "cardReady": True,
        "actionTitle": "先找红围巾，再洗脸",
        "context": "她焦虑时，先安抚。",
        "mainAction": "先确认红围巾，再带她去洗漱。",
        "steps": ["看一眼床头抽屉。", "先温水擦手。", "说女儿等会儿来。"],
        "script": "“周阿姨，围巾在这儿。我们洗把脸，等会儿女儿来。”",
        "expected": "情绪稳，愿意洗脸。",
        "learningCue": "点选是否配合。",
        "reminder": "别说她记错了。",
        "safetyLevel": "medium",
        "safetyTitle": "需遵循机构流程",
        "safetyText": "异常就停，按机构流程。",
        "confidenceNote": "红围巾和女儿线索多次有效。",
        "reasoning": "她找围巾会急。围巾和女儿能安抚。",
        "safetyReason": "只是沟通提醒，不是医疗判断。",
        "evidence": [
            {"type": "家属", "source": "女儿", "time": "07-02", "confidence": "高", "text": "红围巾能安抚。"},
            {"type": "观察", "source": "早班", "time": "今天", "confidence": "中高", "text": "她一直找围巾。"},
            {"type": "反馈", "source": "早班", "time": "07-03", "confidence": "高", "text": "先围巾，再洗脸，有效。"},
        ],
    },
    {
        "id": "t2",
        "elderId": "liu",
        "time": "09:00",
        "title": "早餐陪餐",
        "status": "执行中",
        "priority": "中优先",
        "risks": ["吞咽风险", "需护士知情"],
        "confidence": 64,
        "confidenceLabel": "中",
        "cardReady": True,
        "actionTitle": "叫刘老师，慢慢吃",
        "context": "陪餐时先放慢。",
        "mainAction": "先叫刘老师，再小口慢吃。",
        "steps": ["确认粥是温的。", "叫“刘老师”。", "咳嗽就停，叫护士。"],
        "script": "“刘老师，粥是温的。我们慢慢吃，不着急。”",
        "expected": "愿意吃，安全吞咽。",
        "learningCue": "点选是否配合、有无咳嗽。",
        "reminder": "别催。咳嗽就停。",
        "safetyLevel": "high",
        "safetyTitle": "需护士确认",
        "safetyText": "吞咽风险。咳嗽、湿哑，马上叫护士。",
        "confidenceNote": "叫刘老师和沪剧有用，但今天吃得慢。",
        "reasoning": "尊称有用。进食变慢，要多观察。",
        "safetyReason": "吞咽问题必须按流程。",
        "evidence": [
            {"type": "家属", "source": "儿子", "time": "07-04", "confidence": "高", "text": "叫刘老师更配合。"},
            {"type": "观察", "source": "早班", "time": "今天", "confidence": "中", "text": "吃得慢，未呛咳。"},
            {"type": "反馈", "source": "王宁", "time": "昨天", "confidence": "中高", "text": "沪剧后愿意吃。"},
        ],
    },
    {
        "id": "t3",
        "elderId": "chen",
        "time": "10:20",
        "title": "如厕转移",
        "status": "需确认",
        "priority": "高风险",
        "risks": ["跌倒高风险", "低置信"],
        "confidence": 42,
        "confidenceLabel": "低",
        "cardReady": True,
        "actionTitle": "先确认，再转移",
        "context": "跌倒风险高。",
        "mainAction": "先叫护士确认，再按流程转移。",
        "steps": ["看地面和助行器。", "先说明，再扶。", "痛、晕、不稳就停。"],
        "script": "“陈奶奶，我先确认一下，再陪您慢慢起身。”",
        "expected": "减少跌倒。",
        "learningCue": "点选是否叫护士。",
        "reminder": "别单独转移。",
        "safetyLevel": "high",
        "safetyTitle": "需人工确认 / 遵循机构流程",
        "safetyText": "高风险。必须人工确认。",
        "confidenceNote": "夜间起身多，脚踝情况不清。",
        "reasoning": "先说明有效，但风险高，要确认。",
        "safetyReason": "跌倒风险必须按流程。",
        "evidence": [
            {"type": "设备", "source": "床边", "time": "今天", "confidence": "中", "text": "夜里起身两次。"},
            {"type": "反馈", "source": "午班", "time": "昨天", "confidence": "中高", "text": "先说明，再起身，有用。"},
            {"type": "确认", "source": "护士", "time": "07-01", "confidence": "低", "text": "脚踝不清，要确认。"},
        ],
    },
    {
        "id": "t4",
        "elderId": "zhou",
        "time": "14:00",
        "title": "午后活动提醒",
        "status": "未生成",
        "priority": "普通",
        "risks": ["情绪波动"],
        "confidence": 58,
        "confidenceLabel": "中",
        "cardReady": False,
        "actionTitle": "先看状态，再活动",
        "context": "午后情况不足。",
        "mainAction": "先看精神，再决定活动。",
        "steps": ["看有没有午睡。", "问想听沪剧吗。", "焦虑就说女儿会来。"],
        "script": "“周阿姨，下午先坐会儿。想听沪剧吗？”",
        "expected": "知道下午适合做什么。",
        "learningCue": "点选精神好不好。",
        "reminder": "先观察，别硬推。",
        "safetyLevel": "medium",
        "safetyTitle": "依据不足，请人工确认",
        "safetyText": "依据不够，先观察。",
        "confidenceNote": "只有早班信息，下午还不清楚。",
        "reasoning": "早上焦虑，不代表下午也一样。",
        "safetyReason": "依据不足时不能说死。",
        "evidence": [
            {"type": "反馈", "source": "早班", "time": "今天", "confidence": "中", "text": "红围巾早上有效。"},
            {"type": "家属", "source": "语音", "time": "07-02", "confidence": "高", "text": "午后喜欢听沪剧。"},
        ],
    },
]


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def decode(value, fallback):
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CursorAdapter:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        if isinstance(row, dict):
            return HybridRow(row)
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [HybridRow(row) if isinstance(row, dict) else row for row in rows]


class DatabaseAdapter:
    def __init__(self, raw, postgres=False):
        self.raw = raw
        self.postgres = postgres

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.raw.rollback()
        else:
            self.raw.commit()
        self.raw.close()

    def _query(self, query):
        if not self.postgres:
            return query
        return query.replace("?", "%s")

    def execute(self, query, params=()):
        if not self.postgres:
            return self.raw.execute(query, params)

        clean = query.strip().rstrip(";")
        needs_id = clean.upper().startswith("INSERT INTO FEEDBACK") or clean.upper().startswith("INSERT INTO AI_PROFILES")
        if needs_id and "RETURNING" not in clean.upper():
            clean = f"{clean} RETURNING id"
        cursor = self.raw.execute(self._query(clean), params)
        lastrowid = None
        if needs_id:
            row = cursor.fetchone()
            if isinstance(row, dict):
                lastrowid = row["id"]
            elif row:
                lastrowid = row[0]
        return CursorAdapter(cursor, lastrowid)

    def executescript(self, script):
        if self.postgres:
            script = script.replace(
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
                "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
            )
            script = script.replace(
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)",
            )
        for statement in script.split(";"):
            sql = statement.strip()
            if sql:
                self.execute(sql)

    def commit(self):
        self.raw.commit()


def connect():
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("Missing psycopg. Run: pip install -r backend/requirements.txt")
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return DatabaseAdapter(conn, postgres=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return DatabaseAdapter(conn, postgres=False)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS elders (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              initial TEXT NOT NULL,
              age INTEGER NOT NULL,
              room TEXT NOT NULL,
              status TEXT NOT NULL,
              contact TEXT NOT NULL,
              mobility TEXT NOT NULL,
              diet TEXT NOT NULL,
              preference_tags TEXT NOT NULL,
              avoid_tags TEXT NOT NULL,
              family_summary TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS observations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              time_label TEXT NOT NULL,
              title TEXT NOT NULL,
              text TEXT NOT NULL,
              tag TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              elder_id TEXT NOT NULL,
              time_label TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              priority TEXT NOT NULL,
              risks TEXT NOT NULL,
              confidence INTEGER NOT NULL,
              confidence_label TEXT NOT NULL,
              card_ready INTEGER NOT NULL,
              action_title TEXT NOT NULL,
              context TEXT NOT NULL,
              main_action TEXT NOT NULL,
              steps TEXT NOT NULL,
              script TEXT NOT NULL,
              expected TEXT NOT NULL,
              learning_cue TEXT NOT NULL,
              reminder TEXT NOT NULL,
              safety_level TEXT NOT NULL,
              safety_title TEXT NOT NULL,
              safety_text TEXT NOT NULL,
              confidence_note TEXT NOT NULL,
              reasoning TEXT NOT NULL,
              safety_reason TEXT NOT NULL,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS evidence (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              type TEXT NOT NULL,
              source TEXT NOT NULL,
              time_label TEXT NOT NULL,
              confidence TEXT NOT NULL,
              text TEXT NOT NULL,
              FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              elder_id TEXT NOT NULL,
              effect TEXT NOT NULL,
              observations TEXT NOT NULL,
              voice_note TEXT NOT NULL,
              note TEXT NOT NULL,
              reaction TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (task_id) REFERENCES tasks(id),
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS ai_profiles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              content TEXT NOT NULL,
              generated_by TEXT NOT NULL,
              model TEXT NOT NULL,
              warning TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM elders").fetchone()[0]
        if count == 0:
            seed(conn)


def seed(conn):
    for elder in SEED_ELDERS:
        conn.execute(
            """
            INSERT INTO elders (
              id, name, initial, age, room, status, contact, mobility, diet,
              preference_tags, avoid_tags, family_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elder["id"],
                elder["name"],
                elder["initial"],
                elder["age"],
                elder["room"],
                elder["status"],
                elder["contact"],
                elder["mobility"],
                elder["diet"],
                encode(elder["preferenceTags"]),
                encode(elder["avoidTags"]),
                encode(elder["familySummary"]),
            ),
        )
        for item in elder["observations"]:
            conn.execute(
                """
                INSERT INTO observations (elder_id, time_label, title, text, tag)
                VALUES (?, ?, ?, ?, ?)
                """,
                (elder["id"], item["time"], item["title"], item["text"], item["tag"]),
            )

    for task in SEED_TASKS:
        conn.execute(
            """
            INSERT INTO tasks (
              id, elder_id, time_label, title, status, priority, risks, confidence,
              confidence_label, card_ready, action_title, context, main_action, steps,
              script, expected, learning_cue, reminder, safety_level, safety_title,
              safety_text, confidence_note, reasoning, safety_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["elderId"],
                task["time"],
                task["title"],
                task["status"],
                task["priority"],
                encode(task["risks"]),
                task["confidence"],
                task["confidenceLabel"],
                1 if task["cardReady"] else 0,
                task["actionTitle"],
                task["context"],
                task["mainAction"],
                encode(task["steps"]),
                task["script"],
                task["expected"],
                task["learningCue"],
                task["reminder"],
                task["safetyLevel"],
                task["safetyTitle"],
                task["safetyText"],
                task["confidenceNote"],
                task["reasoning"],
                task["safetyReason"],
            ),
        )
        for item in task["evidence"]:
            conn.execute(
                """
                INSERT INTO evidence (task_id, type, source, time_label, confidence, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task["id"], item["type"], item["source"], item["time"], item["confidence"], item["text"]),
            )


def elder_from_row(row, observations):
    return {
        "id": row["id"],
        "name": row["name"],
        "initial": row["initial"],
        "age": row["age"],
        "room": row["room"],
        "status": row["status"],
        "contact": row["contact"],
        "mobility": row["mobility"],
        "diet": row["diet"],
        "preferenceTags": decode(row["preference_tags"], []),
        "avoidTags": decode(row["avoid_tags"], []),
        "familySummary": decode(row["family_summary"], []),
        "observations": observations,
    }


def task_from_row(row, evidence_items):
    return {
        "id": row["id"],
        "elderId": row["elder_id"],
        "time": row["time_label"],
        "title": row["title"],
        "status": row["status"],
        "priority": row["priority"],
        "risks": decode(row["risks"], []),
        "confidence": row["confidence"],
        "confidenceLabel": row["confidence_label"],
        "cardReady": bool(row["card_ready"]),
        "actionTitle": row["action_title"],
        "context": row["context"],
        "mainAction": row["main_action"],
        "steps": decode(row["steps"], []),
        "script": row["script"],
        "expected": row["expected"],
        "learningCue": row["learning_cue"],
        "reminder": row["reminder"],
        "safetyLevel": row["safety_level"],
        "safetyTitle": row["safety_title"],
        "safetyText": row["safety_text"],
        "confidenceNote": row["confidence_note"],
        "reasoning": row["reasoning"],
        "safetyReason": row["safety_reason"],
        "evidence": evidence_items,
    }


def get_elders(conn):
    rows = conn.execute("SELECT * FROM elders ORDER BY room").fetchall()
    result = {}
    for row in rows:
        observation_rows = conn.execute(
            """
            SELECT time_label, title, text, tag
            FROM observations
            WHERE elder_id = ?
            ORDER BY id DESC
            LIMIT 8
            """,
            (row["id"],),
        ).fetchall()
        observations = [
            {"time": item["time_label"], "title": item["title"], "text": item["text"], "tag": item["tag"]}
            for item in observation_rows
        ]
        result[row["id"]] = elder_from_row(row, observations)
    return result


def get_tasks(conn):
    rows = conn.execute("SELECT * FROM tasks ORDER BY time_label").fetchall()
    result = []
    for row in rows:
        evidence_rows = conn.execute(
            """
            SELECT type, source, time_label, confidence, text
            FROM evidence
            WHERE task_id = ?
            ORDER BY id
            """,
            (row["id"],),
        ).fetchall()
        evidence_items = [
            {
                "type": item["type"],
                "source": item["source"],
                "time": item["time_label"],
                "confidence": item["confidence"],
                "text": item["text"],
            }
            for item in evidence_rows
        ]
        result.append(task_from_row(row, evidence_items))
    return result


def get_feedback(conn, task_id=None):
    if task_id:
        rows = conn.execute(
            """
            SELECT * FROM feedback
            WHERE task_id = ?
            ORDER BY id DESC
            """,
            (task_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 50").fetchall()
    return [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "elder_id": row["elder_id"],
            "effect": row["effect"],
            "observations": decode(row["observations"], []),
            "voice_note": row["voice_note"],
            "note": row["note"],
            "reaction": row["reaction"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_ai_profiles(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM ai_profiles
            WHERE elder_id = ?
            ORDER BY id DESC
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT p.*
            FROM ai_profiles p
            JOIN (
              SELECT elder_id, MAX(id) AS max_id
              FROM ai_profiles
              GROUP BY elder_id
            ) latest ON p.id = latest.max_id
            ORDER BY p.id DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "content": decode(row["content"], {}),
            "generated_by": row["generated_by"],
            "model": row["model"],
            "warning": row["warning"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def latest_ai_profile_map(conn):
    result = {}
    for item in get_ai_profiles(conn):
        result[item["elder_id"]] = item
    return result


def gather_profile_context(conn, elder_id):
    elders = get_elders(conn)
    elder = elders.get(elder_id)
    if not elder:
        raise ValueError("elder_id not found")
    all_tasks = get_tasks(conn)
    tasks_for_elder = [task for task in all_tasks if task["elderId"] == elder_id]
    task_ids = {task["id"] for task in tasks_for_elder}
    feedback = [item for item in get_feedback(conn) if item["elder_id"] == elder_id or item["task_id"] in task_ids]
    external_records = fetch_external_records(elder_id)
    return {
        "elder": elder,
        "tasks": tasks_for_elder,
        "feedback": feedback[:20],
        "external_records": external_records[:50],
    }


def save_ai_profile(conn, elder_id, result):
    now = dt.datetime.now().isoformat(timespec="seconds")
    profile = result.get("profile", {})
    generated_by = result.get("generated_by", "unknown")
    model = result.get("model", "")
    warning = result.get("warning", "")
    cur = conn.execute(
        """
        INSERT INTO ai_profiles (elder_id, content, generated_by, model, warning, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (elder_id, encode(profile), generated_by, model, warning, now),
    )
    return {
        "id": cur.lastrowid,
        "elder_id": elder_id,
        "content": profile,
        "generated_by": generated_by,
        "model": model,
        "warning": warning,
        "created_at": now,
    }


def sync_external_records(conn, elder_id):
    records = fetch_external_records(elder_id)
    now = dt.datetime.now().isoformat(timespec="seconds")
    inserted = 0
    for record in records:
        text = record.get("text", "").strip()
        if not text:
            continue
        exists = conn.execute(
            """
            SELECT id FROM observations
            WHERE elder_id = ? AND text = ? AND tag = ?
            LIMIT 1
            """,
            (elder_id, text, record.get("type", "外部")),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                elder_id,
                record.get("time") or dt.datetime.now().strftime("%H:%M"),
                record.get("source") or "外部系统",
                text,
                record.get("type") or "外部",
                now,
            ),
        )
        inserted += 1
    return {"records": records, "inserted": inserted}


def create_feedback(conn, payload):
    task_id = str(payload.get("task_id") or "").strip()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise ValueError("task_id not found")

    elder_id = str(payload.get("elder_id") or task["elder_id"]).strip()
    effect = str(payload.get("effect") or "有效").strip()
    observations = payload.get("observations") or []
    if not isinstance(observations, list):
        observations = [str(observations)]
    voice_note = str(payload.get("voice_note") or "").strip()
    note = str(payload.get("note") or "").strip()
    observation_text = "、".join([str(item) for item in observations if str(item).strip()]) or "未选择观察项"
    reaction = "；".join([item for item in [observation_text, voice_note, note] if item]) or "只交结果。"
    now = dt.datetime.now()
    created_at = now.isoformat(timespec="seconds")
    time_label = now.strftime("%H:%M")

    cur = conn.execute(
        """
        INSERT INTO feedback (
          task_id, elder_id, effect, observations, voice_note, note, reaction, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, elder_id, effect, encode(observations), voice_note, note, reaction, created_at),
    )
    conn.execute(
        """
        INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (elder_id, time_label, f"{task['title']}反馈 · {effect}", reaction, "反馈", created_at),
    )
    return {
        "id": cur.lastrowid,
        "task_id": task_id,
        "elder_id": elder_id,
        "effect": effect,
        "observations": observations,
        "voice_note": voice_note,
        "note": note,
        "reaction": reaction,
        "created_at": created_at,
        "time": time_label,
    }


class CareActionHandler(BaseHTTPRequestHandler):
    server_version = "CareActionBackend/1.0"

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self.send_json({"ok": True, "database": str(DB_PATH), "time": dt.datetime.now().isoformat()})
            if path == "/api/bootstrap":
                with connect() as conn:
                    return self.send_json({
                        "elders": get_elders(conn),
                        "tasks": get_tasks(conn),
                        "feedback": get_feedback(conn),
                        "ai_profiles": latest_ai_profile_map(conn),
                    })
            if path == "/api/integrations/status":
                return self.send_json(integration_status())
            if path == "/api/source/records":
                query = parse_qs(parsed.query)
                elder_id = query.get("elder_id", [""])[0]
                if not elder_id:
                    return self.send_json({"error": "elder_id required"}, status=400)
                return self.send_json({"records": fetch_external_records(elder_id)})
            if path == "/api/elders":
                with connect() as conn:
                    return self.send_json({"elders": get_elders(conn)})
            if path == "/api/tasks":
                with connect() as conn:
                    return self.send_json({"tasks": get_tasks(conn)})
            if path.startswith("/api/tasks/"):
                task_id = unquote(path.removeprefix("/api/tasks/"))
                with connect() as conn:
                    task = next((item for item in get_tasks(conn) if item["id"] == task_id), None)
                    if not task:
                        return self.send_json({"error": "task not found"}, status=404)
                    return self.send_json({"task": task})
            if path == "/api/feedback":
                query = parse_qs(parsed.query)
                task_id = query.get("task_id", [None])[0]
                with connect() as conn:
                    return self.send_json({"feedback": get_feedback(conn, task_id)})
            if path == "/api/ai/profiles":
                with connect() as conn:
                    return self.send_json({"profiles": get_ai_profiles(conn)})
            if path.startswith("/api/ai/profile/"):
                elder_id = unquote(path.removeprefix("/api/ai/profile/"))
                with connect() as conn:
                    profiles = get_ai_profiles(conn, elder_id)
                    if not profiles:
                        return self.send_json({"profile": None})
                    return self.send_json({"profile": profiles[0]})
            return self.send_static(path)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/feedback":
                payload = self.read_json()
                with connect() as conn:
                    item = create_feedback(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "feedback": item}, status=201)
            if parsed.path == "/api/source/sync":
                payload = self.read_json()
                elder_id = str(payload.get("elder_id") or "").strip()
                if not elder_id:
                    return self.send_json({"error": "elder_id required"}, status=400)
                with connect() as conn:
                    result = sync_external_records(conn, elder_id)
                    conn.commit()
                return self.send_json({"ok": True, **result})
            if parsed.path == "/api/ai/profile/generate":
                payload = self.read_json()
                elder_id = str(payload.get("elder_id") or "").strip()
                if not elder_id:
                    return self.send_json({"error": "elder_id required"}, status=400)
                with connect() as conn:
                    context = gather_profile_context(conn, elder_id)
                    generated = generate_care_profile(context)
                    saved = save_ai_profile(conn, elder_id, generated)
                    conn.commit()
                return self.send_json({"ok": True, "profile": saved}, status=201)
            return self.send_json({"error": "not found"}, status=404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, status=500)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        safe_path = Path(unquote(path.lstrip("/")))
        full_path = (ROOT / safe_path).resolve()
        if ROOT not in full_path.parents and full_path != ROOT:
            return self.send_json({"error": "forbidden"}, status=403)
        if not full_path.exists() or not full_path.is_file():
            return self.send_json({"error": "not found"}, status=404)
        content = full_path.read_bytes()
        mime = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), CareActionHandler)
    print(f"CareAction backend running: http://127.0.0.1:{PORT}")
    print(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
