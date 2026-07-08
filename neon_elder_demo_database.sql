-- CareAction external elder database demo for Neon/PostgreSQL
-- Usage: paste this whole file into Neon SQL Editor and run.
-- This is a demo "institution database" that CareAction can read as an external source.

BEGIN;

CREATE TABLE IF NOT EXISTS residents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  gender TEXT NOT NULL,
  birth_year INTEGER NOT NULL,
  room TEXT NOT NULL,
  care_level TEXT NOT NULL,
  cognition_status TEXT NOT NULL,
  mobility TEXT NOT NULL,
  diet TEXT NOT NULL,
  medical_notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS family_contacts (
  id BIGSERIAL PRIMARY KEY,
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  relation TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resident_preferences (
  id BIGSERIAL PRIMARY KEY,
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  detail TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT '中',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS care_experience_library (
  id BIGSERIAL PRIMARY KEY,
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  method TEXT NOT NULL,
  result TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT '中',
  safety_boundary TEXT NOT NULL DEFAULT '医疗、急救、约束、高风险操作遵循机构流程。',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_care_schedule (
  id BIGSERIAL PRIMARY KEY,
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  time_label TEXT NOT NULL,
  task_type TEXT NOT NULL,
  task_title TEXT NOT NULL,
  risk_level TEXT NOT NULL DEFAULT '普通',
  status TEXT NOT NULL DEFAULT '待执行',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- This table is intentionally shaped for CareAction's default external query:
-- SELECT type, source, time_label AS time, text, confidence
-- FROM care_records
-- WHERE elder_id = %s
-- ORDER BY time_label DESC
-- LIMIT 50
CREATE TABLE IF NOT EXISTS care_records (
  id BIGSERIAL PRIMARY KEY,
  elder_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  time_label TEXT NOT NULL,
  text TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT '中',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO residents (
  id, name, gender, birth_year, room, care_level, cognition_status, mobility, diet, medical_notes
) VALUES
  ('zhou', '周雅琴', '女', 1944, '302', '二级护理', '轻中度认知障碍，早晨容易焦虑和重复询问', '可扶行，晨间需看护', '软食，偏好温热饮', '注意情绪安抚；非医疗建议以机构医护判断为准'),
  ('liu', '刘建国', '男', 1950, '218', '三级护理', '认知基本稳定，午后易疲劳', '可独立坐起，进食时需陪看', '半流质，需小口慢食', '轻度吞咽风险，咳嗽、湿哑需立即通知护士'),
  ('chen', '陈淑芬', '女', 1938, '115', '一级护理', '夜间起身多，转移前需反复确认', '夜间起身需陪同，转移需人工确认', '清淡软食', '跌倒高风险，转移必须遵循机构流程')
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  gender = EXCLUDED.gender,
  birth_year = EXCLUDED.birth_year,
  room = EXCLUDED.room,
  care_level = EXCLUDED.care_level,
  cognition_status = EXCLUDED.cognition_status,
  mobility = EXCLUDED.mobility,
  diet = EXCLUDED.diet,
  medical_notes = EXCLUDED.medical_notes;

INSERT INTO family_contacts (resident_id, name, relation, phone, notes) VALUES
  ('zhou', '周敏', '女儿', '', '红围巾和“女儿等会儿来”能安抚周雅琴。不要说她记错。'),
  ('liu', '刘洋', '儿子', '', '称呼“刘老师”时更愿意回应。饭前听沪剧有帮助。'),
  ('chen', '林可', '孙女', '', '转移前一定先说明，不要突然扶。夜里起身多，注意防跌倒。');

INSERT INTO resident_preferences (resident_id, category, label, detail, source, confidence) VALUES
  ('zhou', '安心线索', '红围巾', '看见红围巾后情绪更稳定，适合洗漱前使用。', '女儿周敏', '高'),
  ('zhou', '沟通禁忌', '不要否定记忆', '不要说“你记错了”，可以说“我们再看一遍”。', '早班经验', '高'),
  ('zhou', '兴趣', '沪剧', '午后听沪剧更容易平静。', '家属补充', '中高'),
  ('liu', '称呼', '刘老师', '用“刘老师”称呼比直接叫名字更配合。', '儿子刘洋', '高'),
  ('liu', '饮食', '热粥', '冷粥容易拒绝，温热粥接受度更高。', '餐食记录', '中高'),
  ('liu', '安全', '慢慢吃', '吞咽风险，必须小口慢食，咳嗽就停。', '护士提醒', '高'),
  ('chen', '沟通方式', '先说明', '转移或扶起前先说明每一步，减少抗拒。', '午班经验', '中高'),
  ('chen', '安全', '不要单独转移', '跌倒高风险，转移必须人工确认。', '护士确认', '高'),
  ('chen', '偏好', '靠窗', '坐靠窗位置时情绪较稳定。', '家属补充', '中')
ON CONFLICT DO NOTHING;

INSERT INTO care_experience_library (
  resident_id, task_type, method, result, source, confidence, safety_boundary
) VALUES
  ('zhou', '洗漱', '先找红围巾，再说女儿等会儿来，最后带去洗脸。', '周雅琴情绪更稳，愿意配合洗漱。', '陈晓岚护工', '高', '只做沟通安抚；异常停止并按机构流程。'),
  ('zhou', '午后活动', '先问想不想听沪剧，再决定是否参加活动。', '减少硬推造成的焦虑。', '家属补充 + 早班观察', '中', '如果疲劳或焦虑明显，先休息。'),
  ('liu', '早餐陪餐', '先叫“刘老师”，确认粥是温的，再小口慢吃。', '进食配合度提高。', '王宁护工', '高', '吞咽异常立即停止并通知护士。'),
  ('liu', '沟通', '不要催第一口，先让他闻到热粥味道。', '拒绝进食次数减少。', '餐食记录', '中', '不强迫进食。'),
  ('chen', '如厕转移', '先说明，再确认地面和助行器，最后按流程转移。', '突然抗拒减少。', '午班护工', '中高', '跌倒高风险，必须人工确认。'),
  ('chen', '夜间照护', '夜间起身先开小夜灯，再陪同站起。', '夜间惊慌减少。', '夜班记录', '中', '必须陪同，不单独下床。')
ON CONFLICT DO NOTHING;

INSERT INTO daily_care_schedule (resident_id, time_label, task_type, task_title, risk_level, status) VALUES
  ('zhou', '08:30', '洗漱', '晨间洗漱协助', '中', '待执行'),
  ('liu', '09:00', '吃饭', '早餐陪餐', '高', '待执行'),
  ('chen', '10:20', '转移', '如厕转移', '高', '需确认'),
  ('zhou', '14:00', '活动', '午后活动提醒', '中', '未生成')
ON CONFLICT DO NOTHING;

INSERT INTO care_records (elder_id, type, source, time_label, text, confidence) VALUES
  ('zhou', '家属输入', '女儿周敏', '2026-07-06 18:20', '红围巾能安抚妈妈。她找不到围巾时会着急，先让她看到围巾再洗漱。', '高'),
  ('zhou', '护理经验', '陈晓岚护工', '2026-07-06 08:45', '先找红围巾，再说女儿等会儿来，周雅琴愿意洗脸。', '高'),
  ('zhou', '观察记录', '早班', '2026-07-07 07:48', '周雅琴反复找围巾，有些焦虑。', '中高'),
  ('zhou', '沟通禁忌', '家属端', '2026-07-05 19:00', '不要直接说她记错了，可以说“我们再看一遍”。', '高'),
  ('zhou', '兴趣爱好', '家属补充', '2026-07-04 16:30', '午后听沪剧时更容易安静坐下。', '中高'),

  ('liu', '家属输入', '儿子刘洋', '2026-07-06 20:10', '爸爸以前是老师，叫他“刘老师”会更愿意回应。', '高'),
  ('liu', '护理经验', '王宁护工', '2026-07-06 09:15', '饭前放一小段沪剧后，刘建国愿意多吃几口。', '中高'),
  ('liu', '观察记录', '早班', '2026-07-07 08:55', '早餐喝粥停顿多，未呛咳。', '中'),
  ('liu', '安全提示', '护士站', '2026-07-06 09:00', '吞咽不顺、咳嗽或声音湿哑时必须停止进食并通知护士。', '高'),
  ('liu', '饮食偏好', '餐食记录', '2026-07-05 08:40', '冷粥会拒绝，温热粥接受度更高。', '中高'),

  ('chen', '安全提示', '护士站', '2026-07-07 06:30', '陈淑芬跌倒高风险，如厕转移必须人工确认并按流程。', '高'),
  ('chen', '设备记录', '床边报警', '2026-07-07 02:15', '夜里床边报警两次，有起身迹象。', '中'),
  ('chen', '护理经验', '午班护工', '2026-07-06 10:40', '先说明“我扶您慢慢起身”，再扶，抗拒明显减少。', '中高'),
  ('chen', '家属输入', '孙女林可', '2026-07-05 21:10', '奶奶不喜欢别人突然扶她，先说清楚会比较安心。', '高'),
  ('chen', '观察记录', '夜班', '2026-07-06 23:30', '夜间起身前开小夜灯，情绪更稳定。', '中')
ON CONFLICT DO NOTHING;

COMMIT;

-- Quick checks after import:
-- SELECT * FROM residents;
-- SELECT type, source, time_label AS time, text, confidence FROM care_records WHERE elder_id = 'zhou' ORDER BY time_label DESC LIMIT 50;
