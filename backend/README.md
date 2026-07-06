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

如果要调用 AI API：

```text
AI_API_BASE=https://api.openai.com/v1
AI_API_KEY=你的AI密钥
AI_MODEL=你的模型名
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
AI_API_BASE=你的AI接口地址
AI_API_KEY=你的AI密钥
AI_MODEL=你的模型名
```

如果还没有 AI Key，可以先不填，后端会使用本地规则生成画像。

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
