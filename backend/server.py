from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import sqlite3

from integrations import (
    fetch_external_records,
    generate_care_profile,
    generate_daily_summary,
    integration_status,
    load_env,
)
from plugin_integrations import generate_plugin_suggestion

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
INSERT_ID_TABLES = {
    "FEEDBACK",
    "AI_PROFILES",
    "LIFE_STORY_CARDS",
    "CARE_EXPERIENCES",
    "TASK_SUGGESTIONS",
    "PENDING_CONFIRMATIONS",
    "FAMILY_STORY_INPUTS",
    "CARE_PHOTOS",
    "RAW_INPUTS",
}


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
        upper = clean.upper()
        needs_id = any(upper.startswith(f"INSERT INTO {table}") for table in INSERT_ID_TABLES)
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

            CREATE TABLE IF NOT EXISTS life_story_cards (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              section TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              care_meaning TEXT NOT NULL,
              confidence TEXT NOT NULL,
              status TEXT NOT NULL,
              evidence TEXT NOT NULL,
              generated_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS care_experiences (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              task_type TEXT NOT NULL,
              method TEXT NOT NULL,
              why_it_works TEXT NOT NULL,
              source TEXT NOT NULL,
              confidence TEXT NOT NULL,
              safety TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS task_suggestions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              elder_id TEXT NOT NULL,
              headline TEXT NOT NULL,
              action TEXT NOT NULL,
              script TEXT NOT NULL,
              safety TEXT NOT NULL,
              source_summary TEXT NOT NULL,
              confidence INTEGER NOT NULL,
              evidence TEXT NOT NULL,
              generated_at TEXT NOT NULL,
              FOREIGN KEY (task_id) REFERENCES tasks(id),
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS pending_confirmations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              suggested_value TEXT NOT NULL,
              source TEXT NOT NULL,
              confidence TEXT NOT NULL,
              status TEXT NOT NULL,
              resolution TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              resolved_at TEXT NOT NULL DEFAULT '',
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS family_story_inputs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              author TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );

            CREATE TABLE IF NOT EXISTS care_photos (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              image_data TEXT NOT NULL,
              caption TEXT NOT NULL,
              created_at TEXT NOT NULL,
              visible_to_family INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY (elder_id) REFERENCES elders(id),
              FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS raw_inputs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              elder_id TEXT NOT NULL,
              source_type TEXT NOT NULL,
              source_name TEXT NOT NULL,
              content_type TEXT NOT NULL,
              content TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              tags TEXT NOT NULL,
              confidence TEXT NOT NULL,
              status TEXT NOT NULL,
              ai_result TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              parsed_at TEXT NOT NULL DEFAULT '',
              FOREIGN KEY (elder_id) REFERENCES elders(id)
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM elders").fetchone()[0]
        if count == 0:
            seed(conn)
        seed_personalization_layer(conn)


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


def seed_personalization_layer(conn):
    if conn.execute("SELECT COUNT(*) FROM care_experiences").fetchone()[0] == 0:
        now = dt.datetime.now().isoformat(timespec="seconds")
        seed_items = [
            {
                "elder_id": "zhou",
                "task_type": "洗漱",
                "method": "先找红围巾，再开始洗漱。",
                "why_it_works": "红围巾和女儿线索能降低焦虑。",
                "source": "家属 + 早班经验",
                "confidence": "高",
                "safety": "只做沟通安抚，异常按机构流程。",
            },
            {
                "elder_id": "liu",
                "task_type": "吃饭",
                "method": "叫“刘老师”，确认粥温热，再小口慢吃。",
                "why_it_works": "尊称和沪剧能提升配合度。",
                "source": "家属 + 王宁经验",
                "confidence": "中高",
                "safety": "吞咽异常马上停下并通知护士。",
            },
            {
                "elder_id": "chen",
                "task_type": "转移",
                "method": "先说明每一步，确认地面和助行器，再慢慢扶起。",
                "why_it_works": "先说明能减少突然被扶的不安。",
                "source": "午班经验 + 护士确认",
                "confidence": "中",
                "safety": "跌倒高风险，需人工确认并遵循机构流程。",
            },
        ]
        for item in seed_items:
            conn.execute(
                """
                INSERT INTO care_experiences (
                  elder_id, task_type, method, why_it_works, source, confidence, safety, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["elder_id"],
                    item["task_type"],
                    item["method"],
                    item["why_it_works"],
                    item["source"],
                    item["confidence"],
                    item["safety"],
                    "active",
                    now,
                ),
            )

    if conn.execute("SELECT COUNT(*) FROM life_story_cards").fetchone()[0] == 0:
        now = dt.datetime.now().isoformat(timespec="seconds")
        seed_cards = [
            {
                "elder_id": "zhou",
                "section": "重要关系",
                "title": "女儿和红围巾是安心线索",
                "content": "周雅琴阿姨想起女儿时情绪更稳定，红围巾能帮助她确认熟悉感。",
                "care_meaning": "洗漱前先让她看到红围巾，再提一句女儿会来。",
                "confidence": "高",
                "evidence": [{"source": "女儿", "time": "07-02", "text": "红围巾能安抚。", "confidence": "高"}],
            },
            {
                "elder_id": "liu",
                "section": "尊严称呼",
                "title": "他更愿意被叫刘老师",
                "content": "刘建国伯伯对“刘老师”的称呼反应更好，吃饭时更愿意配合。",
                "care_meaning": "陪餐开头先叫刘老师，语速放慢。",
                "confidence": "高",
                "evidence": [{"source": "儿子", "time": "07-04", "text": "叫刘老师更配合。", "confidence": "高"}],
            },
            {
                "elder_id": "chen",
                "section": "安全边界",
                "title": "转移前要先说明和确认",
                "content": "陈淑芬奶奶不喜欢突然被扶，夜间起身多，转移前需要先说明并确认安全。",
                "care_meaning": "如厕转移必须先人工确认，再按流程慢慢扶。",
                "confidence": "中",
                "evidence": [{"source": "午班", "time": "昨天", "text": "先说明，再起身，有用。", "confidence": "中高"}],
            },
        ]
        for card in seed_cards:
            conn.execute(
                """
                INSERT INTO life_story_cards (
                  elder_id, section, title, content, care_meaning, confidence, status,
                  evidence, generated_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["elder_id"],
                    card["section"],
                    card["title"],
                    card["content"],
                    card["care_meaning"],
                    card["confidence"],
                    "active",
                    encode(card["evidence"]),
                    "seed",
                    now,
                ),
            )

    if conn.execute("SELECT COUNT(*) FROM pending_confirmations").fetchone()[0] == 0:
        now = dt.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO pending_confirmations (
              elder_id, title, content, suggested_value, source, confidence, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "zhou",
                "确认午后活动偏好",
                "系统多次看到“午后听沪剧”有效，但还需要家属确认是否每天都适用。",
                "午后活动前可先问要不要听沪剧。",
                "家属语音 + 早班反馈",
                "低",
                "pending",
                now,
            ),
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


def list_from_payload(value, fallback=None, max_items=12):
    if isinstance(value, list):
        source = value
    else:
        source = (
            str(value or "")
            .replace("，", ",")
            .replace("、", ",")
            .replace("；", ",")
            .replace(";", ",")
            .split(",")
        )
    items = [str(item).strip() for item in source if str(item).strip()]
    return (items[:max_items] or (fallback or []))[:max_items]


def unique_elder_id(conn, proposed):
    base = "".join(
        char.lower() if char.isascii() and char.isalnum() else "_"
        for char in str(proposed or "")
    ).strip("_")
    if not base:
        base = f"elder_{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    base = base[:36]
    candidate = base
    suffix = 2
    while conn.execute("SELECT id FROM elders WHERE id = ?", (candidate,)).fetchone():
        candidate = f"{base[:30]}_{suffix}"
        suffix += 1
    return candidate


def create_elder(conn, payload):
    name = str(payload.get("name") or "").strip()
    room = str(payload.get("room") or "").strip()
    if not name:
        raise ValueError("name required")
    if not room:
        raise ValueError("room required")
    try:
        age = int(payload.get("age") or 0)
    except (TypeError, ValueError):
        raise ValueError("age invalid")
    if age < 0 or age > 120:
        raise ValueError("age invalid")

    initial = str(payload.get("initial") or name[:1]).strip()[:2] or "新"
    status = str(payload.get("status") or "待评估").strip()[:80]
    contact = str(payload.get("contact") or "待补充").strip()[:80]
    mobility = str(payload.get("mobility") or "待补充").strip()[:120]
    diet = str(payload.get("diet") or "待补充").strip()[:120]
    preference_tags = list_from_payload(payload.get("preference_tags") or payload.get("preferenceTags"))
    avoid_tags = list_from_payload(payload.get("avoid_tags") or payload.get("avoidTags"))
    family_summary = list_from_payload(payload.get("family_summary") or payload.get("familySummary"), max_items=6)
    note = str(payload.get("note") or "").strip()
    if note and not family_summary:
        family_summary = [note[:120]]

    elder_id = unique_elder_id(conn, payload.get("id") or f"{room}_{name}")
    conn.execute(
        """
        INSERT INTO elders (
          id, name, initial, age, room, status, contact, mobility, diet,
          preference_tags, avoid_tags, family_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            elder_id,
            name,
            initial,
            age,
            room,
            status,
            contact,
            mobility,
            diet,
            encode(preference_tags),
            encode(avoid_tags),
            encode(family_summary),
        ),
    )
    now = dt.datetime.now().isoformat(timespec="seconds")
    if note:
        conn.execute(
            """
            INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (elder_id, "入院", "入院备注", note[:500], "登记", now),
        )
    row = conn.execute("SELECT * FROM elders WHERE id = ?", (elder_id,)).fetchone()
    observations = []
    if note:
        observations = [{"time": "入院", "title": "入院备注", "text": note[:500], "tag": "登记"}]
    return elder_from_row(row, observations)


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


def get_life_story_cards(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM life_story_cards
            WHERE elder_id = ?
            ORDER BY id DESC
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM life_story_cards ORDER BY id DESC LIMIT 100").fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "section": row["section"],
            "title": row["title"],
            "content": row["content"],
            "care_meaning": row["care_meaning"],
            "confidence": row["confidence"],
            "status": row["status"],
            "evidence": decode(row["evidence"], []),
            "generated_by": row["generated_by"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_care_experiences(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM care_experiences
            WHERE elder_id = ?
            ORDER BY id DESC
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM care_experiences ORDER BY id DESC LIMIT 100").fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "task_type": row["task_type"],
            "method": row["method"],
            "why_it_works": row["why_it_works"],
            "source": row["source"],
            "confidence": row["confidence"],
            "safety": row["safety"],
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_task_suggestions(conn, task_id=None):
    if task_id:
        rows = conn.execute(
            """
            SELECT * FROM task_suggestions
            WHERE task_id = ?
            ORDER BY id DESC
            """,
            (task_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT s.*
            FROM task_suggestions s
            JOIN (
              SELECT task_id, MAX(id) AS max_id
              FROM task_suggestions
              GROUP BY task_id
            ) latest ON s.id = latest.max_id
            ORDER BY s.generated_at DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "elder_id": row["elder_id"],
            "headline": row["headline"],
            "action": row["action"],
            "script": row["script"],
            "safety": row["safety"],
            "source_summary": row["source_summary"],
            "confidence": row["confidence"],
            "evidence": decode(row["evidence"], []),
            "generated_at": row["generated_at"],
        }
        for row in rows
    ]


def latest_task_suggestion_map(conn):
    return {item["task_id"]: item for item in get_task_suggestions(conn)}


def get_pending_confirmations(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM pending_confirmations
            WHERE elder_id = ?
            ORDER BY id DESC
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pending_confirmations ORDER BY id DESC LIMIT 100").fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "title": row["title"],
            "content": row["content"],
            "suggested_value": row["suggested_value"],
            "source": row["source"],
            "confidence": row["confidence"],
            "status": row["status"],
            "resolution": row["resolution"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }
        for row in rows
    ]


def get_family_story_inputs(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM family_story_inputs
            WHERE elder_id = ?
            ORDER BY id DESC
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM family_story_inputs ORDER BY id DESC LIMIT 100").fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "author": row["author"],
            "content": row["content"],
            "created_at": row["created_at"],
            "status": row["status"],
        }
        for row in rows
    ]


def get_care_photos(conn, elder_id=None):
    if elder_id:
        rows = conn.execute(
            """
            SELECT * FROM care_photos
            WHERE elder_id = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (elder_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM care_photos ORDER BY id DESC LIMIT 30").fetchall()
    return [
        {
            "id": row["id"],
            "elder_id": row["elder_id"],
            "task_id": row["task_id"],
            "image_data": row["image_data"],
            "caption": row["caption"],
            "created_at": row["created_at"],
            "visible_to_family": bool(row["visible_to_family"]),
        }
        for row in rows
    ]


def raw_input_from_row(row):
    return {
        "id": row["id"],
        "elder_id": row["elder_id"],
        "source_type": row["source_type"],
        "source_name": row["source_name"],
        "content_type": row["content_type"],
        "content": row["content"],
        "occurred_at": row["occurred_at"],
        "tags": decode(row["tags"], []),
        "confidence": row["confidence"],
        "status": row["status"],
        "ai_result": decode(row["ai_result"], {}) if row["ai_result"] else {},
        "created_at": row["created_at"],
        "parsed_at": row["parsed_at"],
    }


def get_raw_inputs(conn, elder_id=None, status=None, limit=100):
    limit = max(1, min(int(limit or 100), 200))
    if elder_id and status:
        rows = conn.execute(
            """
            SELECT * FROM raw_inputs
            WHERE elder_id = ? AND status = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (elder_id, status, limit),
        ).fetchall()
    elif elder_id:
        rows = conn.execute(
            """
            SELECT * FROM raw_inputs
            WHERE elder_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (elder_id, limit),
        ).fetchall()
    elif status:
        rows = conn.execute(
            """
            SELECT * FROM raw_inputs
            WHERE status = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM raw_inputs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [raw_input_from_row(row) for row in rows]


def suggestion_for_task(task, suggestion=None):
    if not suggestion:
        return {
            "task_id": task["id"],
            "elder_id": task["elderId"],
            "headline": task["actionTitle"],
            "action": task["mainAction"],
            "script": task["script"],
            "safety": task["safetyText"],
            "source_summary": task["confidenceNote"],
            "confidence": task["confidence"],
            "evidence": task["evidence"],
            "generated_at": "",
        }
    return suggestion


def get_current_task_payload(conn):
    tasks = get_tasks(conn)
    suggestions = latest_task_suggestion_map(conn)
    current = next((task for task in tasks if task["status"] not in ("已完成", "完成")), None) or (tasks[-1] if tasks else None)
    if not current:
        return {"task": None, "elder": None, "suggestion": None, "remaining": 0}
    elders = get_elders(conn)
    remaining = len([task for task in tasks if task["status"] not in ("已完成", "完成")])
    return {
        "task": current,
        "elder": elders.get(current["elderId"]),
        "suggestion": suggestion_for_task(current, suggestions.get(current["id"])),
        "remaining": remaining,
    }


def plugin_shift_payload():
    now = dt.datetime.now()
    hour = now.hour
    if 7 <= hour < 15:
        name = "早班"
        period = "07:00-15:00"
    elif 15 <= hour < 22:
        name = "中班"
        period = "15:00-22:00"
    else:
        name = "夜班"
        period = "22:00-07:00"
    return {
        "name": name,
        "period": period,
        "date": now.strftime("%Y-%m-%d"),
        "caregiver": os.environ.get("PLUGIN_CAREGIVER_NAME", "护理员"),
    }


def plugin_task_type(task):
    text = " ".join([str(task.get("title", "")), " ".join(str(item) for item in task.get("risks", []))])
    rules = [
        ("进食", ["饭", "餐", "食", "粥", "吞咽"]),
        ("洗漱", ["洗", "漱", "脸", "口腔"]),
        ("转移", ["转移", "如厕", "起身", "行走", "跌倒"]),
        ("活动", ["活动", "散步", "音乐", "沪剧"]),
        ("情绪安抚", ["焦虑", "抗拒", "情绪", "陪伴"]),
    ]
    for task_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return task_type
    return "日常照护"


def plugin_is_completed(status):
    text = str(status or "").strip().lower()
    return text in {"done", "complete", "completed", "已完成", "完成"} or "完成" in text


def plugin_risk_level(task):
    text = " ".join(
        [
            str(task.get("priority", "")),
            str(task.get("safetyLevel", "")),
            str(task.get("safetyTitle", "")),
            str(task.get("safetyText", "")),
            " ".join(str(item) for item in task.get("risks", [])),
        ]
    )
    if any(keyword in text for keyword in ["高", "吞咽", "跌倒", "转移", "用药", "急救", "约束"]):
        return "high"
    if any(keyword in text for keyword in ["中", "确认", "观察"]):
        return "medium"
    return "normal"


def plugin_pick_tag(items, keywords=None, fallback="未录入"):
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    if keywords:
        for value in values:
            if any(keyword in value for keyword in keywords):
                return value
    return values[0] if values else fallback


def plugin_elder_core_profile(elder):
    preferences = elder.get("preferenceTags", []) if elder else []
    avoids = elder.get("avoidTags", []) if elder else []
    family = elder.get("familySummary", []) if elder else []
    return {
        "称呼": plugin_pick_tag(preferences, ["老师", "校长", "阿姨", "叔", "伯", "奶"], elder.get("name", "未录入") if elder else "未录入"),
        "禁忌": plugin_pick_tag(avoids, fallback="未录入"),
        "偏好": plugin_pick_tag(preferences or family, fallback="未录入"),
    }


def plugin_task_card(task, elder, suggestion=None):
    return {
        "task_id": task["id"],
        "elder_id": task["elderId"],
        "time": task["time"],
        "task_title": task["title"],
        "task_type": plugin_task_type(task),
        "status": task["status"],
        "completed": plugin_is_completed(task["status"]),
        "risk_level": plugin_risk_level(task),
        "risks": task.get("risks", []),
        "elder_name": elder.get("name", ""),
        "room": elder.get("room", ""),
        "elder_status": elder.get("status", ""),
        "core_profile": plugin_elder_core_profile(elder),
        "has_ai_suggestion": bool(suggestion),
        "suggestion_headline": suggestion.get("headline", "") if suggestion else "",
    }


def get_plugin_caregiver_tasks_payload(conn):
    elders = get_elders(conn)
    suggestions = latest_task_suggestion_map(conn)
    tasks = [plugin_task_card(task, elders.get(task["elderId"], {}), suggestions.get(task["id"])) for task in get_tasks(conn)]
    return {
        "ok": True,
        "shift": plugin_shift_payload(),
        "summary": {
            "total": len(tasks),
            "pending": len([task for task in tasks if not task["completed"]]),
            "completed": len([task for task in tasks if task["completed"]]),
        },
        "tasks": tasks,
    }


def plugin_find_task(conn, task_id):
    task = next((item for item in get_tasks(conn) if item["id"] == task_id), None)
    if not task:
        raise ValueError("task_id not found")
    elders = get_elders(conn)
    elder = elders.get(task["elderId"])
    if not elder:
        raise ValueError("elder not found")
    return task, elder


def gather_plugin_suggestion_context(conn, task_id, staff_level="normal"):
    task, elder = plugin_find_task(conn, task_id)
    try:
        external_records = fetch_external_records(elder["id"])
    except Exception:
        external_records = []
    return {
        "task": task,
        "elder": elder,
        "staff_level": staff_level,
        "feedback": get_feedback(conn, task_id)[:20],
        "raw_inputs": get_raw_inputs(conn, elder_id=elder["id"], limit=50),
        "family_inputs": get_family_story_inputs(conn, elder["id"])[:30],
        "life_story_cards": get_life_story_cards(conn, elder["id"])[:30],
        "care_experiences": get_care_experiences(conn, elder["id"])[:30],
        "pending_confirmations": get_pending_confirmations(conn, elder["id"])[:20],
        "external_records": external_records[:50],
    }


def plugin_steps_from_action(action, fallback=None):
    text = str(action or "").strip()
    if not text:
        return fallback or []
    for sep in ["\n", "；", ";", "。"]:
        if sep in text:
            return [item.strip() for item in text.split(sep) if item.strip()][:3]
    return [text]


def plugin_suggestion_response(task, elder, suggestion, cached=False, generated_by="database", model="", warning=""):
    steps = suggestion.get("steps") or plugin_steps_from_action(suggestion.get("action"), [task.get("mainAction", "")])
    return {
        "ok": True,
        "cached": cached,
        "task_id": task["id"],
        "elder_id": elder["id"],
        "headline": suggestion.get("headline") or task.get("actionTitle") or task.get("title"),
        "steps": steps[:3],
        "script": suggestion.get("script") or task.get("script", ""),
        "safety": suggestion.get("safety") or task.get("safetyText", ""),
        "source_summary": suggestion.get("source_summary") or task.get("confidenceNote", ""),
        "confidence": int(suggestion.get("confidence") or task.get("confidence") or 60),
        "evidence": suggestion.get("evidence") or task.get("evidence", []),
        "generated_by": generated_by,
        "model": model,
        "warning": warning,
    }


def save_plugin_task_suggestion(conn, task, generated):
    now = dt.datetime.now().isoformat(timespec="seconds")
    suggestion = generated.get("suggestion") or {}
    steps = [str(item).strip() for item in suggestion.get("steps", []) if str(item).strip()]
    cur = conn.execute(
        """
        INSERT INTO task_suggestions (
          task_id, elder_id, headline, action, script, safety, source_summary,
          confidence, evidence, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task["id"],
            task["elderId"],
            str(suggestion.get("headline") or task.get("actionTitle") or task.get("title")),
            "\n".join(steps) or str(task.get("mainAction") or ""),
            str(suggestion.get("script") or task.get("script") or ""),
            str(suggestion.get("safety") or task.get("safetyText") or "遵循机构流程，必要时人工确认。"),
            str(suggestion.get("source_summary") or task.get("confidenceNote") or ""),
            int(suggestion.get("confidence") or task.get("confidence") or 60),
            encode(suggestion.get("evidence") or task.get("evidence") or []),
            now,
        ),
    )
    saved = get_task_suggestions(conn, task["id"])[0]
    saved["id"] = cur.lastrowid
    return saved


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
    raw_inputs = get_raw_inputs(conn, elder_id=elder_id, limit=50)
    return {
        "elder": elder,
        "tasks": tasks_for_elder,
        "feedback": feedback[:20],
        "raw_inputs": raw_inputs,
        "external_records": external_records[:50],
    }


def gather_daily_summary_context(conn):
    return {
        "elders": get_elders(conn),
        "tasks": get_tasks(conn),
        "feedback": get_feedback(conn)[:80],
        "raw_inputs": get_raw_inputs(conn, limit=120),
        "family_inputs": get_family_story_inputs(conn)[:80],
        "life_story_cards": get_life_story_cards(conn)[:100],
        "care_experiences": get_care_experiences(conn)[:100],
        "pending_confirmations": [
            item for item in get_pending_confirmations(conn) if item["status"] == "pending"
        ][:50],
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


def save_daily_summary(conn, result):
    now = dt.datetime.now().isoformat(timespec="seconds")
    summary = result.get("summary", {})
    generated_by = result.get("generated_by", "unknown")
    model = result.get("model", "")
    warning = result.get("warning", "")
    saved = {"story_cards": [], "care_experiences": [], "task_suggestions": [], "pending_confirmations": []}

    conn.execute("DELETE FROM task_suggestions")

    for card in summary.get("story_cards", [])[:40]:
        elder_id = str(card.get("elder_id") or "").strip()
        if not elder_id:
            continue
        cur = conn.execute(
            """
            INSERT INTO life_story_cards (
              elder_id, section, title, content, care_meaning, confidence, status,
              evidence, generated_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elder_id,
                str(card.get("section") or "照护要点"),
                str(card.get("title") or "新的故事卡"),
                str(card.get("content") or ""),
                str(card.get("care_meaning") or ""),
                str(card.get("confidence") or "中"),
                str(card.get("status") or "active"),
                encode(card.get("evidence") or []),
                generated_by,
                now,
            ),
        )
        saved["story_cards"].append(cur.lastrowid)

    for item in summary.get("care_experiences", [])[:40]:
        elder_id = str(item.get("elder_id") or "").strip()
        if not elder_id:
            continue
        cur = conn.execute(
            """
            INSERT INTO care_experiences (
              elder_id, task_type, method, why_it_works, source, confidence, safety, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elder_id,
                str(item.get("task_type") or "通用照护"),
                str(item.get("method") or ""),
                str(item.get("why_it_works") or ""),
                str(item.get("source") or generated_by),
                str(item.get("confidence") or "中"),
                str(item.get("safety") or "医疗和高风险事项按机构流程。"),
                str(item.get("status") or "active"),
                now,
            ),
        )
        saved["care_experiences"].append(cur.lastrowid)

    for item in summary.get("task_suggestions", [])[:80]:
        task_id = str(item.get("task_id") or "").strip()
        elder_id = str(item.get("elder_id") or "").strip()
        if not task_id or not elder_id:
            continue
        cur = conn.execute(
            """
            INSERT INTO task_suggestions (
              task_id, elder_id, headline, action, script, safety, source_summary,
              confidence, evidence, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                elder_id,
                str(item.get("headline") or ""),
                str(item.get("action") or ""),
                str(item.get("script") or ""),
                str(item.get("safety") or "异常就停，按机构流程。"),
                str(item.get("source_summary") or ""),
                int(item.get("confidence") or 60),
                encode(item.get("evidence") or []),
                now,
            ),
        )
        saved["task_suggestions"].append(cur.lastrowid)

    for item in summary.get("pending_confirmations", [])[:30]:
        elder_id = str(item.get("elder_id") or "").strip()
        if not elder_id:
            continue
        cur = conn.execute(
            """
            INSERT INTO pending_confirmations (
              elder_id, title, content, suggested_value, source, confidence, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elder_id,
                str(item.get("title") or "待确认信息"),
                str(item.get("content") or ""),
                str(item.get("suggested_value") or ""),
                str(item.get("source") or generated_by),
                str(item.get("confidence") or "低"),
                str(item.get("status") or "pending"),
                now,
            ),
        )
        saved["pending_confirmations"].append(cur.lastrowid)

    return {"saved": saved, "generated_by": generated_by, "model": model, "warning": warning, "created_at": now}


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


def create_family_story_input(conn, payload):
    elder_id = str(payload.get("elder_id") or "").strip()
    if not elder_id:
        raise ValueError("elder_id required")
    if not conn.execute("SELECT id FROM elders WHERE id = ?", (elder_id,)).fetchone():
        raise ValueError("elder_id not found")
    author = str(payload.get("author") or "家属").strip()
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("content required")
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO family_story_inputs (elder_id, author, content, created_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (elder_id, author, content, now, "pending_summary"),
    )
    conn.execute(
        """
        INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (elder_id, dt.datetime.now().strftime("%H:%M"), "家属补充", content, "家属", now),
    )
    return {
        "id": cur.lastrowid,
        "elder_id": elder_id,
        "author": author,
        "content": content,
        "created_at": now,
        "status": "pending_summary",
    }


def resolve_confirmation(conn, confirmation_id, payload):
    row = conn.execute("SELECT * FROM pending_confirmations WHERE id = ?", (confirmation_id,)).fetchone()
    if not row:
        raise ValueError("confirmation not found")
    action = str(payload.get("action") or "confirm").strip()
    edited_value = str(payload.get("value") or row["suggested_value"]).strip()
    now = dt.datetime.now().isoformat(timespec="seconds")
    status = {"confirm": "confirmed", "edit": "edited", "deny": "denied"}.get(action, action)
    conn.execute(
        """
        UPDATE pending_confirmations
        SET status = ?, resolution = ?, resolved_at = ?
        WHERE id = ?
        """,
        (status, edited_value, now, confirmation_id),
    )
    if status in ("confirmed", "edited") and edited_value:
        cur = conn.execute(
            """
            INSERT INTO life_story_cards (
              elder_id, section, title, content, care_meaning, confidence, status,
              evidence, generated_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["elder_id"],
                "家属确认",
                row["title"],
                edited_value,
                "后续照护建议可引用这条已确认信息。",
                "高",
                "active",
                encode([{"source": row["source"], "time": row["created_at"], "text": row["content"], "confidence": row["confidence"]}]),
                "family-confirmed",
                now,
            ),
        )
        story_card_id = cur.lastrowid
    else:
        story_card_id = None
    return {"id": confirmation_id, "status": status, "resolution": edited_value, "story_card_id": story_card_id}


def complete_task(conn, task_id, payload):
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise ValueError("task not found")
    now = dt.datetime.now()
    created_at = now.isoformat(timespec="seconds")
    note = str(payload.get("note") or "已完成").strip()
    voice_note = str(payload.get("voice_note") or "").strip()
    effect = str(payload.get("effect") or "已完成").strip()
    observations = payload.get("observations") or []
    if not isinstance(observations, list):
        observations = [str(observations)]
    reaction = "；".join([item for item in ["已完成", voice_note, note if note != "已完成" else ""] if item])
    cur = conn.execute(
        """
        INSERT INTO feedback (
          task_id, elder_id, effect, observations, voice_note, note, reaction, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, task["elder_id"], effect, encode(observations), voice_note, note, reaction, created_at),
    )
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", ("已完成", task_id))
    conn.execute(
        """
        INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task["elder_id"], now.strftime("%H:%M"), f"{task['title']}完成", reaction, "完成", created_at),
    )
    return {"id": cur.lastrowid, "task_id": task_id, "elder_id": task["elder_id"], "created_at": created_at}


def reset_tasks(conn):
    reset_items = []
    for task in SEED_TASKS:
        status = task.get("status") or "待执行"
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task["id"]))
        reset_items.append({"id": task["id"], "status": status})
    return reset_items


def create_help_request(conn, task_id, payload):
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise ValueError("task not found")
    now = dt.datetime.now()
    created_at = now.isoformat(timespec="seconds")
    note = str(payload.get("note") or "需要帮助").strip()
    conn.execute(
        """
        INSERT INTO observations (elder_id, time_label, title, text, tag, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task["elder_id"], now.strftime("%H:%M"), f"{task['title']}需要帮助", note, "求助", created_at),
    )
    return {"task_id": task_id, "elder_id": task["elder_id"], "note": note, "created_at": created_at}


def save_care_photos(conn, payload):
    elder_id = str(payload.get("elder_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    photos = payload.get("photos") or []
    caption = str(payload.get("caption") or "").strip()
    if not elder_id or not task_id:
        raise ValueError("elder_id and task_id required")
    if not isinstance(photos, list):
        raise ValueError("photos must be a list")
    now = dt.datetime.now().isoformat(timespec="seconds")
    saved = []
    for image_data in photos[:3]:
        text = str(image_data or "")
        if not text.startswith("data:image/"):
            continue
        cur = conn.execute(
            """
            INSERT INTO care_photos (elder_id, task_id, image_data, caption, created_at, visible_to_family)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (elder_id, task_id, text, caption, now, 1),
        )
        saved.append(cur.lastrowid)
    return {"saved": saved, "created_at": now}


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


def create_raw_input(conn, payload):
    elder_id = str(payload.get("elder_id") or "").strip()
    if not elder_id:
        raise ValueError("elder_id required")
    elder = conn.execute("SELECT id FROM elders WHERE id = ?", (elder_id,)).fetchone()
    if not elder:
        raise ValueError("elder_id not found")

    source_type = str(payload.get("source_type") or "admin").strip()[:40]
    source_name = str(payload.get("source_name") or "").strip()[:80]
    content_type = str(payload.get("content_type") or "text").strip()[:40]
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("content required")
    if len(content) > 6000:
        raise ValueError("content too long")

    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(tag).strip() for tag in tags if str(tag).strip()][:12]

    confidence = str(payload.get("confidence") or "medium").strip()[:20]
    occurred_at = str(payload.get("occurred_at") or "").strip()
    now = dt.datetime.now()
    created_at = now.isoformat(timespec="seconds")
    if not occurred_at:
        occurred_at = created_at

    cur = conn.execute(
        """
        INSERT INTO raw_inputs (
          elder_id, source_type, source_name, content_type, content, occurred_at,
          tags, confidence, status, ai_result, created_at, parsed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            elder_id,
            source_type,
            source_name,
            content_type,
            content,
            occurred_at,
            encode(tags),
            confidence,
            "pending_ai_parse",
            "",
            created_at,
            "",
        ),
    )
    return {
        "id": cur.lastrowid,
        "elder_id": elder_id,
        "source_type": source_type,
        "source_name": source_name,
        "content_type": content_type,
        "content": content,
        "occurred_at": occurred_at,
        "tags": tags,
        "confidence": confidence,
        "status": "pending_ai_parse",
        "ai_result": {},
        "created_at": created_at,
        "parsed_at": "",
    }


def infer_raw_input_task_type(content, tags):
    text = content + " " + " ".join(tags)
    rules = [
        ("进食", ["吃", "饭", "粥", "餐", "吞咽", "呛", "喝"]),
        ("洗漱", ["洗", "脸", "澡", "口腔", "牙", "擦身"]),
        ("如厕", ["厕所", "如厕", "小便", "大便", "二便"]),
        ("翻身", ["翻身", "褥疮", "压疮", "减压", "卧床"]),
        ("服药", ["药", "服药", "医嘱", "吗啡", "降糖"]),
        ("活动", ["散步", "活动", "下棋", "听", "音乐", "沪剧"]),
        ("情绪安抚", ["焦虑", "抗拒", "情绪", "生气", "哭", "配合"]),
    ]
    for task_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return task_type
    return "日常照护"


def parse_raw_input(conn, raw_input_id):
    row = conn.execute("SELECT * FROM raw_inputs WHERE id = ?", (raw_input_id,)).fetchone()
    if not row:
        raise ValueError("raw input not found")
    raw = raw_input_from_row(row)
    content = raw["content"]
    tags = raw["tags"]
    task_type = infer_raw_input_task_type(content, tags)
    summary = content[:42] + ("…" if len(content) > 42 else "")
    has_risk = any(
        keyword in content
        for keyword in ["药", "吗啡", "急救", "跌倒", "吞咽", "呛咳", "约束", "出血", "发热", "体温", "疼痛", "医嘱"]
    )
    safety = "涉及医疗、用药、急救、跌倒、吞咽异常时，必须遵循机构流程并通知护士/医生。" if has_risk else "这只是个性化照护提醒，不替代专业医疗判断。"
    source = raw["source_name"] or raw["source_type"]
    now = dt.datetime.now().isoformat(timespec="seconds")

    result = {
        "summary": summary,
        "risk_level": "high" if has_risk else "normal",
        "task_type": task_type,
        "life_story_cards": [
            {
                "elder_id": raw["elder_id"],
                "section": "原始资料整理",
                "title": tags[0] if tags else f"{task_type}线索",
                "content": content,
                "care_meaning": f"后续{task_type}任务可参考这条信息，但需要人工确认。",
                "confidence": raw["confidence"],
                "status": "pending",
                "evidence": [{"source": source, "raw_input_id": raw_input_id, "occurred_at": raw["occurred_at"]}],
            }
        ],
        "care_experiences": [
            {
                "elder_id": raw["elder_id"],
                "task_type": task_type,
                "method": content,
                "why_it_works": "来自原始资料录入，需结合后续反馈验证。",
                "source": source,
                "confidence": raw["confidence"],
                "safety": safety,
                "status": "pending",
            }
        ],
        "pending_confirmations": [
            {
                "elder_id": raw["elder_id"],
                "title": f"确认{task_type}线索",
                "content": content,
                "suggested_value": summary,
                "source": source,
                "confidence": raw["confidence"],
                "status": "pending",
            }
        ],
        "boundary": safety,
    }

    saved = {"story_cards": [], "care_experiences": [], "pending_confirmations": []}
    for card in result["life_story_cards"]:
        cur = conn.execute(
            """
            INSERT INTO life_story_cards (
              elder_id, section, title, content, care_meaning, confidence, status,
              evidence, generated_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card["elder_id"],
                card["section"],
                card["title"],
                card["content"],
                card["care_meaning"],
                card["confidence"],
                card["status"],
                encode(card["evidence"]),
                "raw_input_rule",
                now,
            ),
        )
        saved["story_cards"].append(cur.lastrowid)

    for item in result["care_experiences"]:
        cur = conn.execute(
            """
            INSERT INTO care_experiences (
              elder_id, task_type, method, why_it_works, source, confidence, safety,
              status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["elder_id"],
                item["task_type"],
                item["method"],
                item["why_it_works"],
                item["source"],
                item["confidence"],
                item["safety"],
                item["status"],
                now,
            ),
        )
        saved["care_experiences"].append(cur.lastrowid)

    for item in result["pending_confirmations"]:
        cur = conn.execute(
            """
            INSERT INTO pending_confirmations (
              elder_id, title, content, suggested_value, source, confidence, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["elder_id"],
                item["title"],
                item["content"],
                item["suggested_value"],
                item["source"],
                item["confidence"],
                item["status"],
                now,
            ),
        )
        saved["pending_confirmations"].append(cur.lastrowid)

    conn.execute(
        """
        UPDATE raw_inputs
        SET status = ?, ai_result = ?, parsed_at = ?
        WHERE id = ?
        """,
        ("parsed_pending_confirmation", encode(result), now, raw_input_id),
    )
    return {"raw_input_id": raw_input_id, "result": result, "saved": saved, "parsed_at": now}


class CareActionHandler(BaseHTTPRequestHandler):
    server_version = "CareActionBackend/1.0"

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CareAction-Key")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def plugin_authorized(self):
        configured = os.environ.get("PLUGIN_API_KEY", "").strip()
        if not configured:
            return True
        return self.headers.get("X-CareAction-Key", "").strip() == configured

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self.send_json({"ok": True, "database": str(DB_PATH), "time": dt.datetime.now().isoformat()})
            if path == "/api/plugin/caregiver/tasks":
                if not self.plugin_authorized():
                    return self.send_json({"error": "unauthorized"}, status=401)
                with connect() as conn:
                    return self.send_json(get_plugin_caregiver_tasks_payload(conn))
            if path == "/api/bootstrap":
                with connect() as conn:
                    return self.send_json({
                        "elders": get_elders(conn),
                        "tasks": get_tasks(conn),
                        "feedback": get_feedback(conn),
                        "ai_profiles": latest_ai_profile_map(conn),
                        "life_story_cards": get_life_story_cards(conn),
                        "care_experiences": get_care_experiences(conn),
                        "task_suggestions": latest_task_suggestion_map(conn),
                        "pending_confirmations": get_pending_confirmations(conn),
                        "family_story_inputs": get_family_story_inputs(conn),
                        "care_photos": get_care_photos(conn),
                        "raw_inputs": get_raw_inputs(conn),
                    })
            if path == "/api/integrations/status":
                return self.send_json(integration_status())
            if path == "/api/current-task":
                with connect() as conn:
                    return self.send_json(get_current_task_payload(conn))
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
            if path == "/api/raw-inputs":
                query = parse_qs(parsed.query)
                elder_id = query.get("elder_id", [None])[0]
                status = query.get("status", [None])[0]
                limit = int(query.get("limit", ["100"])[0])
                with connect() as conn:
                    return self.send_json({"raw_inputs": get_raw_inputs(conn, elder_id, status, limit)})
            if path.startswith("/api/raw-inputs/"):
                raw_input_id = int(unquote(path.removeprefix("/api/raw-inputs/")))
                with connect() as conn:
                    row = conn.execute("SELECT * FROM raw_inputs WHERE id = ?", (raw_input_id,)).fetchone()
                    if not row:
                        return self.send_json({"error": "raw input not found"}, status=404)
                    return self.send_json({"raw_input": raw_input_from_row(row)})
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
            if path.startswith("/api/life-story/"):
                elder_id = unquote(path.removeprefix("/api/life-story/"))
                with connect() as conn:
                    return self.send_json({"cards": get_life_story_cards(conn, elder_id)})
            if path.startswith("/api/care-experiences/"):
                elder_id = unquote(path.removeprefix("/api/care-experiences/"))
                with connect() as conn:
                    return self.send_json({"experiences": get_care_experiences(conn, elder_id)})
            if path.startswith("/api/confirmations/"):
                elder_id = unquote(path.removeprefix("/api/confirmations/"))
                with connect() as conn:
                    return self.send_json({"confirmations": get_pending_confirmations(conn, elder_id)})
            if path.startswith("/api/photos/"):
                elder_id = unquote(path.removeprefix("/api/photos/"))
                with connect() as conn:
                    return self.send_json({"photos": get_care_photos(conn, elder_id)})
            return self.send_static(path)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/plugin/suggestions":
                if not self.plugin_authorized():
                    return self.send_json({"error": "unauthorized"}, status=401)
                payload = self.read_json()
                task_id = str(payload.get("task_id") or "").strip()
                if not task_id:
                    return self.send_json({"error": "task_id required"}, status=400)
                force_refresh = bool(payload.get("force_refresh"))
                staff_level = str(payload.get("staff_level") or "normal").strip()
                with connect() as conn:
                    task, elder = plugin_find_task(conn, task_id)
                    cached = get_task_suggestions(conn, task_id)
                    if cached and not force_refresh:
                        return self.send_json(plugin_suggestion_response(task, elder, cached[0], cached=True))
                    context = gather_plugin_suggestion_context(conn, task_id, staff_level)
                    generated = generate_plugin_suggestion(context)
                    saved = save_plugin_task_suggestion(conn, task, generated)
                    conn.commit()
                    return self.send_json(
                        plugin_suggestion_response(
                            task,
                            elder,
                            saved,
                            cached=False,
                            generated_by=generated.get("generated_by", "unknown"),
                            model=generated.get("model", ""),
                            warning=generated.get("warning", ""),
                        ),
                        status=201,
                    )
            if parsed.path == "/api/plugin/feedback":
                if not self.plugin_authorized():
                    return self.send_json({"error": "unauthorized"}, status=401)
                payload = self.read_json()
                with connect() as conn:
                    item = create_feedback(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "feedback": item}, status=201)
            if parsed.path == "/api/daily-summary":
                with connect() as conn:
                    context = gather_daily_summary_context(conn)
                    generated = generate_daily_summary(context)
                    saved = save_daily_summary(conn, generated)
                    conn.commit()
                    return self.send_json({"ok": True, "summary": generated.get("summary", {}), **saved}, status=201)
            if parsed.path == "/api/family/story-input":
                payload = self.read_json()
                with connect() as conn:
                    item = create_family_story_input(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "story_input": item}, status=201)
            if parsed.path == "/api/photos":
                payload = self.read_json()
                with connect() as conn:
                    result = save_care_photos(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, **result}, status=201)
            if parsed.path == "/api/tasks/reset":
                with connect() as conn:
                    reset_items = reset_tasks(conn)
                    conn.commit()
                    return self.send_json({"ok": True, "tasks": reset_items}, status=201)
            if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/complete"):
                task_id = unquote(parsed.path.removeprefix("/api/tasks/").removesuffix("/complete"))
                payload = self.read_json()
                with connect() as conn:
                    result = complete_task(conn, task_id, payload)
                    current = get_current_task_payload(conn)
                    conn.commit()
                return self.send_json({"ok": True, "completed": result, "current": current}, status=201)
            if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/help"):
                task_id = unquote(parsed.path.removeprefix("/api/tasks/").removesuffix("/help"))
                payload = self.read_json()
                with connect() as conn:
                    result = create_help_request(conn, task_id, payload)
                    conn.commit()
                return self.send_json({"ok": True, "help": result}, status=201)
            if parsed.path.startswith("/api/confirmations/") and parsed.path.endswith("/resolve"):
                confirmation_id = unquote(parsed.path.removeprefix("/api/confirmations/").removesuffix("/resolve"))
                payload = self.read_json()
                with connect() as conn:
                    result = resolve_confirmation(conn, int(confirmation_id), payload)
                    conn.commit()
                return self.send_json({"ok": True, "confirmation": result})
            if parsed.path == "/api/feedback":
                payload = self.read_json()
                with connect() as conn:
                    item = create_feedback(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "feedback": item}, status=201)
            if parsed.path == "/api/elders":
                payload = self.read_json()
                with connect() as conn:
                    elder = create_elder(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "elder": elder}, status=201)
            if parsed.path == "/api/raw-inputs":
                payload = self.read_json()
                with connect() as conn:
                    item = create_raw_input(conn, payload)
                    conn.commit()
                return self.send_json({"ok": True, "raw_input": item}, status=201)
            if parsed.path.startswith("/api/raw-inputs/") and parsed.path.endswith("/parse"):
                raw_input_id = int(unquote(parsed.path.removeprefix("/api/raw-inputs/").removesuffix("/parse")))
                with connect() as conn:
                    result = parse_raw_input(conn, raw_input_id)
                    conn.commit()
                return self.send_json({"ok": True, **result}, status=201)
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
            path = "/caregiver_software.html"
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
