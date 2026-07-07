# CareAction SQLite 本地后端

## 启动

双击：

`backend/start_backend.bat`

或在本目录运行：

```bash
python server.py
```

启动后打开：

`http://127.0.0.1:3000`

## 数据库

首次启动会自动创建：

`backend/careaction.sqlite3`

里面包含：

- 老人档案
- 今日任务
- 建议依据
- 护理反馈
- 近期观察

## 常用接口

```text
GET  /api/health
GET  /api/bootstrap
GET  /api/elders
GET  /api/tasks
GET  /api/tasks/t1
GET  /api/feedback
POST /api/feedback
GET  /api/integrations/status
GET  /api/source/records?elder_id=zhou
POST /api/source/sync
GET  /api/ai/profiles
GET  /api/ai/profile/zhou
POST /api/ai/profile/generate
```

## 接入外部数据库 / API / AI

复制配置模板：

```bash
copy .env.example .env
```

然后编辑 `.env`。

如果对方给的是 REST API：

```text
EXTERNAL_SOURCE_TYPE=api
EXTERNAL_API_RECORDS_URL=https://example.com/api/records?elder_id={elder_id}
EXTERNAL_API_TOKEN=对方给的token
```

如果对方给的是可访问的 SQLite 导出库：

```text
EXTERNAL_SOURCE_TYPE=sqlite
EXTERNAL_SQLITE_PATH=C:\path\to\third_party.sqlite3
EXTERNAL_SQLITE_QUERY=SELECT type, source, time_label AS time, text, confidence FROM care_records WHERE elder_id = ? LIMIT 50
```

如果对方给的是 PostgreSQL / Neon 只读库：

```text
EXTERNAL_SOURCE_TYPE=postgres
EXTERNAL_POSTGRES_URL=postgresql://readonly_user:password@host/dbname?sslmode=require
EXTERNAL_POSTGRES_QUERY=SELECT type, source, time_label AS time, text, confidence FROM care_records WHERE elder_id = %s ORDER BY time_label DESC LIMIT 50
```

外部查询结果至少要能映射出这些字段：

```text
type        记录类型，例如 家属输入 / 护理记录 / 观察 / 经验
source      来源，例如 家属端 / 护理系统 / 张护工
time        时间
text        内容
confidence 置信度，高 / 中 / 低
```

如果要调用 DeepSeek AI API：

```text
AI_PROVIDER=openai-compatible
AI_API_BASE=https://api.deepseek.com
AI_API_KEY=你的DeepSeek API Key
AI_MODEL=deepseek-v4-pro
```

未配置 `AI_API_KEY` 时，`/api/ai/profile/generate` 会使用本地规则生成画像，便于先跑通流程。

## 免费云部署：Render + Neon

适合没有银行卡的学生演示。

### 1. 创建 Neon 免费数据库

1. 打开 `https://neon.com`
2. 用 GitHub 或邮箱注册
3. 新建 Project
4. 复制连接串，形如：

```text
postgresql://user:password@host/dbname?sslmode=require
```

### 2. 部署 Render 免费后端

1. 打开 `https://render.com`
2. 用 GitHub 登录
3. 把本项目上传到 GitHub
4. 在 Render 选择 New -> Blueprint
5. 选择这个仓库
6. Render 会读取根目录的 `render.yaml`
7. 在 Environment 里填写：

```text
DATABASE_URL=Neon给你的连接串
AI_API_BASE=https://api.deepseek.com
AI_API_KEY=你的DeepSeek API Key
AI_MODEL=deepseek-v4-pro
EXTERNAL_SOURCE_TYPE=none
```

如果还没有 AI Key，可以先不填，后端会使用本地规则生成画像。

如果要接外部 PostgreSQL，再加：

```text
EXTERNAL_SOURCE_TYPE=postgres
EXTERNAL_POSTGRES_URL=对方给你的只读Postgres连接串
EXTERNAL_POSTGRES_QUERY=对方字段对应后的查询SQL
```

### 3. 打开 Render 地址

部署成功后，Render 会给一个地址，例如：

```text
https://careaction-backend.onrender.com
```

测试：

```text
https://careaction-backend.onrender.com/api/health
```

### 4. APK 连接云后端

在 `index.html` 里把：

```js
window.CAREACTION_API_BASE = "https://careaction-backend.onrender.com";
```

放到脚本前面，或把现有 `API_BASES` 里的局域网地址换成 Render 地址。

## 安卓 APK 连接电脑后端

手机不能用 `127.0.0.1` 访问电脑后端。

当前电脑局域网 IP：

`192.168.31.142`

然后在 `index.html` 里把接口地址改成：

```js
window.CAREACTION_API_BASE = "http://192.168.31.142:3000";
```

电脑和手机必须连同一个 Wi-Fi。

## 配置自检

本地或 Render Shell 里运行：

```bash
python backend/check_config.py
```

它会检查：

- CareAction 自己的数据库是否连通
- 外部数据源是否能读取记录
- DeepSeek API 是否能返回结果

脚本会隐藏密钥，只显示连接状态。
