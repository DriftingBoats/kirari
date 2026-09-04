# Kirari

[English](README.md) | [简体中文](README.zh-CN.md)

Kirari 是一个以 Telegram 为主要入口、也支持本地网页聊天的私人伴侣 Agent。主模型通过 ChatGPT 套餐包含的 Codex CLI 登录运行，不依赖 Hermes，也不需要 OpenAI API Key。你可以选择配置 Gemini API Key，但它只负责语义记忆的向量嵌入，不参与聊天生成。

项目把伴侣产品层和模型运行时明确分开：

```text
Telegram / 本地网页聊天
          ↓
Kirari（对话、记忆、审核、日程、安全边界）
          ↓
Codex CLI（`codex exec`，使用 ChatGPT 账户登录）
```

## 已有能力

- 用可编辑 Markdown 固化身份、关系风格与边界。
- 结合近期对话上下文和可检索的长期记忆。
- 把任意消息固定为长期记忆。
- 每日 Dream/Feel 整理，并校验结构化输出。
- 对推断事实、承诺、边界、提醒和日历事件进行人工审核。
- 可选的 Telegram 主动关心，支持空闲时间、冷却时间和免打扰时段。
- 一次性及日/周/月循环提醒，并支持稍后提醒。
- Telegram Mini App 控制面板和本地网页聊天。
- 完全本地部署时可使用 Telegram 长轮询，同时保留 webhook 模式。
- 本地 SQLite 对话记录、记忆文件版本和回滚。

语音、图片生成、头像与多伴侣暂时不属于核心范围。Kirari 当前优先保证伴侣 Agent 最重要的基础：稳定身份、连续关系、记忆控制、适度主动性，以及用户可见、可干预的治理机制。

## 项目目录

```text
kirari/
├── app/
│   ├── main.py                 # FastAPI 应用、接口与后台任务
│   ├── agent.py                # Codex 订阅运行时适配器
│   ├── companion.py            # 伴侣回复结构与记忆强化
│   ├── config.py               # 环境变量配置
│   ├── db.py                   # SQLite 结构与可重建投影
│   ├── memory_store.py         # Markdown 记忆桶的权威存储
│   ├── memory_service.py       # 存储、合并、归档、恢复与软删除
│   ├── retrieval.py            # 混合检索与自动复现
│   ├── embeddings.py           # 可选的 Gemini 向量索引
│   ├── memory_lifecycle.py     # 强化、衰减与归档生命周期
│   ├── memory_files.py         # SOUL/PINNED/USER/FEEL/DREAM 文件管理
│   ├── dream.py                # Dream/Feel 记忆整理
│   ├── proactive.py            # 可选的主动关心
│   ├── reminders.py            # 循环提醒与稍后提醒
│   ├── telegram.py             # Telegram 轮询、Webhook 与消息持久化
│   ├── telegram_webapp.py      # Telegram Mini App 身份校验
│   └── schemas.py              # API 请求模型
├── static/
│   ├── index.html              # 单页控制台
│   ├── app.css                 # 中文优先的响应式视觉系统
│   └── app.js                  # 前端状态、导航和 API 调用
├── tests/                      # 运行时、记忆、鉴权和审核测试
├── docs/ROADMAP.md             # 产品路线图
├── .env.example                # 安全的配置模板
├── .impeccable.md              # 持久化前端设计方向
├── SECURITY.md                 # 安全与隐私说明
├── pyproject.toml              # Python 项目元数据
└── requirements.txt            # 运行依赖
```

运行数据不会进入 Git 跟踪的源码目录：

```text
data/
├── kirari.sqlite3              # 对话历史和可重建索引
└── memory/
    ├── SOUL.md / PINNED.md / USER.md / MEMORY.md
    ├── FEEL.md / DREAM.md / BOARD.md
    └── buckets/
        ├── active/{领域}/{记忆ID}.md
        ├── archive/{领域}/{记忆ID}.md
        └── tombstone/{领域}/{记忆ID}.md
```

## Codex 订阅运行时

Kirari 使用非交互、临时、只读模式启动 `codex exec`，复用 `codex login` 保存的登录状态。每次调用前都会移除继承到进程中的 `OPENAI_API_KEY` 和 `CODEX_API_KEY`，避免意外切换到 API 计费。

该模式适合运行在你本人控制的电脑上。不要把 `~/.codex/auth.json` 复制到公共服务器或提交到仓库，其中含有账户访问令牌。ChatGPT/Codex 订阅用量与 OpenAI API 计费是彼此独立的产品。

## 环境要求

- Python 3.10+
- Codex CLI
- 拥有 Codex 权限的 ChatGPT 账户
- 可选：通过 BotFather 创建的 Telegram Bot

验证订阅登录：

```bash
codex login
codex login status
```

状态应显示 `Logged in using ChatGPT`。在 Windows 上，Kirari 会优先选择原生 `codex.exe`，避免调用较旧的 npm shim；也可以通过 `CODEX_BIN` 指定可执行文件的完整路径。

## 安装

```bash
git clone https://github.com/DriftingBoats/kirari.git
cd kirari
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS/Linux：

```bash
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

仅使用本地网页聊天时，`.env` 最低配置如下：

```dotenv
APP_DATA_DIR=./data
KIRARI_ACCESS_KEY=请填写一个足够长的随机值
APP_TIMEZONE=Asia/Shanghai

CODEX_BIN=codex
CODEX_REASONING_EFFORT=low
```

启动 Kirari：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

打开 <http://127.0.0.1:8080/>。控制面板会显示 Codex 是否已安装，以及当前是否通过 ChatGPT 登录。

## Telegram：本地长轮询（推荐）

在 `.env` 中加入：

```dotenv
TELEGRAM_BOT_TOKEN=替换为你的Token
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_MODE=polling
```

重启 Kirari。程序会移除已有 webhook，并直接从这台电脑通过 Telegram 长轮询接收消息。务必填写 `TELEGRAM_ALLOWED_USER_IDS`；如果白名单为空，任何发现该 Bot 的人都可能消耗你的 Codex 订阅用量。

不要同时为同一个 Bot 运行长轮询和 webhook 消费端。

## Telegram：Webhook 模式

只有当 Kirari 位于公共 HTTPS 地址之后，并且该机器能安全保存你的 Codex 登录状态时才使用该模式：

```dotenv
BASE_URL=https://example.com
TELEGRAM_MODE=webhook
TELEGRAM_WEBHOOK_SECRET=替换为足够长的随机值
```

注册 webhook：

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## 记忆模型

默认情况下，人类可直接阅读的权威记忆存放在 `./data/memory/`：

- `SOUL.md`：身份、语气、价值观和关系风格，由用户控制。
- `PINNED.md`：承诺、边界和不可违背的规则，由用户控制。
- `USER.md`：关于用户的稳定事实。
- `MEMORY.md`：双方长期共享的经历。
- `FEEL.md`：第一人称关系感受，不作为客观事实。
- `DREAM.md`：每日整理日志。
- `BOARD.md`：留言板与主动消息存档。

可以通过 `KIRARI_MEMORY_DIR` 把这些文件放到其他位置。每次生成回复时都会读取最新文件，因此编辑后无需重启即可在下一轮对话生效。

长期事件记忆采用“一条记录一个 Markdown 桶”，路径为 `memory/buckets/{active,archive,tombstone}/{domain}/`。YAML frontmatter 保存情绪坐标、重要度、激活次数、来源消息 ID、合并谱系和操作足迹，正文保留完整记忆文本。Markdown 桶是权威数据源，SQLite、FTS 和向量只是随时可以重建的投影。启动时会自动把旧版仅存在于 SQLite 的记忆导出为桶，并保留原始数据。

语义记忆采用参考 Ombre-Brain 的混合方案。`gemini-embedding-001` 生成可丢弃重建的 SQLite 向量投影；文档使用 `RETRIEVAL_DOCUMENT`，查询使用 `RETRIEVAL_QUERY`，768 维向量在余弦相似度计算前进行归一化。最终排序综合 Gemini 向量、FTS5/BM25、中文二元词组、RapidFuzz、主题、重要度和记忆生命力，并支持领域、标签、日期、最低重要度和是否包含归档等过滤条件。Gemini 不可用时，会回退到 Codex 订阅重排，再回退到本地混合词法检索。

如需真正的向量检索，可把 Google AI Studio 免费层密钥写入 `.env`：

```dotenv
GEMINI_EMBEDDING_API_KEY=替换为你的密钥
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_EMBEDDING_DIMENSIONS=768
```

使用免费层意味着被索引的记忆文本会发送给 Google；Google 当前声明免费层输入可能用于改进其产品。不要为不愿发送给该服务的敏感记忆启用该能力。

记忆桶成功提交后，新建或修改的记忆会进入持久化后台索引队列。失败任务采用指数退避，重启后仍会继续；已有记忆会在启动时自动对账。`POST /api/memory-index/reindex` 可重建投影，传入 `{ "force": true, "wait": true }` 可立即执行完整重建。

创建普通事实、事件或模式记忆前，Kirari 会搜索兼容的已有记忆。精确或高置信度命中时，会合并原文、标签、实体、来源和谱系，而不是制造重复记录。受保护的 Feel、承诺、边界、计划、信件、置顶和永久记忆不会被隐式合并。

搜索本身不会改变记忆状态。伴侣的结构化输出只上报真正影响本次回答的记忆 ID，随后系统才进行显式强化，并对前后 48 小时内最多五条相关记忆产生轻微激活涟漪。超过六小时没有对话后，新对话还会收到一个有上限的无查询复现集合，其中包含核心记忆、冷启动记忆、近期记忆、鲜明记忆，以及少量随机旧记忆。

自然遗忘只会归档，不会物理删除。参考 Ombre 的生命力评分会综合重要度、激活巩固、指数衰减、短长期时间/情绪权重、resolved/digested 状态和紧迫度。置顶、Feel、承诺、边界、计划、信件和永久记忆均受保护。归档记录仍能被搜索和恢复。`DELETE /api/memories/{id}` 只会创建可恢复的 tombstone，系统不提供公共物理清除接口。自动衰减默认每 24 小时执行一次，可通过 `MEMORY_DECAY_ENABLED=false` 关闭。

Dream 产生的普通记忆同样进入去重桶流程；第一人称 Feel 沉淀则保存为带来源消息的受保护记忆。当一条新 Feel 与至少两条旧 Feel 在语义上接近时，Kirari 会创建一条审核提案，建议把反复出现的主题结晶为置顶记忆。

## 主动消息

主动联系默认关闭，需要显式启用：

```dotenv
PROACTIVE_ENABLED=true
PROACTIVE_IDLE_HOURS=18
PROACTIVE_COOLDOWN_HOURS=24
PROACTIVE_QUIET_START=23
PROACTIVE_QUIET_END=8
```

Kirari 只会在用户长时间未活动后主动联系，并遵守冷却时间和本地免打扰时段。提示词会明确禁止给用户施加内疚感或强迫用户回复。

定时每日反思同样需要主动开启，因为它会消耗订阅用量。设置 `DREAM_SCHEDULE_ENABLED=true` 并通过 `DREAM_HOUR=4` 指定小时；控制面板始终可以手动触发反思。

## API 概览

- `GET /api/status`：Codex 订阅登录和调度器状态。
- `POST /api/chat`：带持久化上下文的本地伴侣聊天。
- `GET /api/messages`：对话历史，可使用 `chat_id` 过滤。
- `POST /api/messages/{id}/pin`：把一条消息固定为记忆。
- `POST /api/memories/{id}/reinforce`：显式强化有用记忆。
- `POST /api/memories/{id}/restore`：恢复归档记忆。
- `GET /api/memories/{id}/trace`：查看来源消息、谱系、足迹和桶路径。
- `GET /api/memories/surface`：预览无查询自动复现。
- `GET /api/memories/feel/search?q=...`：搜索受保护的 Feel 沉淀。
- `POST /api/memories/decay`：预览或执行归档衰减。
- `POST /api/memory-index/reindex`：对账或重建 Gemini 向量。
- `GET|PUT /api/files/{name}`：查看伴侣文件及版本。
- `GET|POST|PATCH|DELETE /api/memories`：管理记忆桶；DELETE 为软删除。
- `GET|POST /api/reviews`：批准或拒绝状态变更提案。
- `GET|POST /api/calendar`：生活、关系和工作事件。
- `GET|POST|PATCH /api/reminders`：提醒、循环和稍后提醒。
- `POST /api/dream/run`：立即执行反思。
- `POST /telegram/webhook`：仅供 webhook 模式使用。

配置 `KIRARI_ACCESS_KEY` 或 `TELEGRAM_BOT_TOKEN` 后，`/api/*` 接口需要访问密钥或有效的 Telegram Mini App init data。

## 测试

```bash
python -m pytest -q
python -m compileall app
```

测试不会调用 Codex，也不会消耗订阅额度。

## 安全

不要提交 `.env`、Telegram Bot Token、`~/.codex/auth.json`、私人记忆文件或 SQLite 数据库。除非已经配置身份验证和 HTTPS，否则控制面板只应绑定在 `127.0.0.1`。

## 相关文档

- [Codex CLI](https://developers.openai.com/codex/cli)
- [Codex 非交互模式](https://developers.openai.com/codex/non-interactive-mode)
- [通过 ChatGPT 套餐使用 Codex](https://help.openai.com/en/articles/11369540)

## 许可证

MIT
