# AIOneWeek Spec 1 — 可实施规格

对应 `Docs/PRD.md` v1.0 · 2026-09-28
形态：本地 localhost 单机 MVP · 技术栈已锁定，实施时不得自行替换

---

## 0. 本 Spec 的边界

**包含**：PRD 第 4 节全部 P0 与 P1 功能，共 8 个可交付单元。
**不含**：云部署、HTTPS、域名、移动端适配、全文搜索、订阅推送、红队测试。

**交付定义**：`python run.py` 启动后，浏览器打开 `http://127.0.0.1:8000` 可完成「注册 → 登录 → 查看当周技术 → 打分 → 管理员查看数据」全链路。

---

## 1. 技术栈（锁定）

| 层 | 选型 | 版本 |
| --- | --- | --- |
| 语言 | Python | ≥ 3.11 |
| Web 框架 | FastAPI | ≥ 0.115 |
| ASGI | uvicorn | ≥ 0.32 |
| ORM | SQLAlchemy | 2.0.x |
| 数据库 | SQLite | 3（stdlib） |
| HTTP 客户端 | httpx | ≥ 0.27 |
| 定时任务 | APScheduler | 3.10.x |
| 加解密 | cryptography（Fernet） | ≥ 43 |
| 邮件 | smtplib + email（stdlib） | — |
| 前端 | 原生 HTML + CSS + JS | 无构建步骤 |

`requirements.txt`

```
fastapi>=0.115
uvicorn[standard]>=0.32
sqlalchemy>=2.0
httpx>=0.27
apscheduler>=3.10
cryptography>=43
python-dotenv>=1.0
```

**前端不得引入任何 npm 依赖、打包器或框架。** 一个 `index.html` + 一个 `app.js` 即可。

---

## 2. 目录结构

```
AIOneWeek/
├── Docs/
│   ├── PRD.md
│   └── Spec1.md
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI 实例、挂载路由与静态文件、启动调度器
│   ├── config.py          # 读取 .env，导出 Settings
│   ├── db.py              # engine / SessionLocal / init_db() / get_db()
│   ├── models.py          # SQLAlchemy ORM 模型（见 §4）
│   ├── schemas.py         # Pydantic 请求/响应模型
│   ├── security.py        # Fernet 加解密、密码格式校验、会话签名
│   ├── mailer.py          # QQ SMTP 发送验证码
│   ├── deepseek.py        # Responses API 调用封装
│   ├── parser.py          # 【】结构化解析
│   ├── collector.py       # 采集编排：幂等、补采、成本累计
│   ├── scheduler.py       # APScheduler 每日 08:50 任务
│   └── routers/
│       ├── __init__.py
│       ├── auth.py        # §6.1
│       ├── weekly.py      # §6.2
│       ├── rating.py      # §6.3
│       └── admin.py       # §6.4
├── static/
│   ├── index.html         # 用户端
│   ├── admin.html         # 管理员端
│   ├── app.js
│   └── style.css
├── data/
│   └── aioneek.db         # git 忽略
├── .env                   # git 忽略
├── .env.example
├── .gitignore
├── requirements.txt
└── run.py                 # uvicorn 启动入口
```

---

## 3. 配置

`.env.example`（真实 `.env` 不入库）

```ini
# DeepSeek —— 走 Anthropic 兼容端点；联网搜索仅该端点可用，见 §5.2
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT=30
DEEPSEEK_MAX_RETRY=2
DEEPSEEK_MAX_TOKENS=4096        # Anthropic 消息格式必填
DEEPSEEK_SEARCH_MAX_USES=3      # 单次采集允许的服务端搜索次数上限

# 加密与会话
FERNET_KEY=          # 生成：python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
SESSION_SECRET=      # 生成：python -c "import secrets;print(secrets.token_urlsafe(32))"

# 邮件（QQ 邮箱，AUTH_CODE 是「授权码」不是登录密码）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=frostyj@qq.com
SMTP_AUTH_CODE=
SMTP_FROM_NAME=AIOneWeek

# 业务
DB_PATH=./data/aioneek.db
ADMIN_EMAIL=frostyj@qq.com
ADMIN_INIT_PASSWORD=      # 首次启动种子管理员用，2-8 位数字+英文
COST_DAILY_LIMIT_CNY=2.0        # 实测单次 ≈ ¥0.024(闲时)/¥0.048(峰时)，见 §9
USD_CNY=7.1                     # 成本换算汇率，仅用于 cost_cny 记账
WEEK_WINDOW_DAYS=7
MAX_ITEMS_PER_DAY=5
CODE_TTL_SECONDS=600
CODE_RESEND_INTERVAL=120
```

**硬性要求**

1. `.gitignore` 必须包含：`.env`、`data/`、`__pycache__/`、`*.db`
2. 代码中**不得出现任何 API key、授权码、密码字面量**，一律经 `config.py` 读取
3. `config.py` 在缺失 `DEEPSEEK_API_KEY` / `FERNET_KEY` / `SESSION_SECRET` 时**启动即报错退出**，不允许静默降级

---

## 4. 数据模型

SQLite，`init_db()` 在启动时建表。日期字段统一 `TEXT` 存 ISO8601（`YYYY-MM-DD` 或完整时间戳）。

### 4.1 `users`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| email | TEXT | UNIQUE NOT NULL |
| password_enc | TEXT | NOT NULL，Fernet 密文 |
| role | TEXT | NOT NULL DEFAULT `'user'`，取值 `user` / `admin` |
| call_count | INTEGER | NOT NULL DEFAULT 0 |
| created_at | TEXT | NOT NULL |

### 4.2 `source_sites`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| url | TEXT | UNIQUE NOT NULL |
| enabled | INTEGER | NOT NULL DEFAULT 1 |
| created_at | TEXT | NOT NULL |

种子数据：`https://huggingface.co/papers/trending`（`enabled=1`）

### 4.3 `daily_run` — 每日采集批次

> **设计说明**：PRD 要求区分「没爬过」与「爬了但没有」。用独立的 run 表承载每日状态，`daily_tech` 只存条目。判定「这周每天都有数据」= `daily_run` 中该日期存在记录（无论 status）。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| date | TEXT | UNIQUE NOT NULL，`YYYY-MM-DD` |
| status | TEXT | NOT NULL，`success` / `empty` / `failed` / `parse_failed` |
| prompt | TEXT | NOT NULL，当次实际发送的完整 prompt |
| raw_response | TEXT | 原始返回全文 |
| item_count | INTEGER | NOT NULL DEFAULT 0 |
| cost_cny | REAL | NOT NULL DEFAULT 0 |
| created_at | TEXT | NOT NULL |
| updated_at | TEXT | NOT NULL |

**status 语义**

| status | 触发条件 | 前端展示 |
| --- | --- | --- |
| `success` | 解析出 ≥1 条 | 正常条目卡片 |
| `empty` | 模型返回「无」 | 「这日无前沿 AI 技术」 |
| `parse_failed` | 有返回但一条都解析不出 | 「该日数据解析异常，管理员可修正」 |
| `failed` | API 报错/超时，重试后仍失败 | 「该日采集失败，稍后自动重试」 |

### 4.4 `daily_tech`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| date | TEXT | NOT NULL，关联 `daily_run.date` |
| seq | INTEGER | NOT NULL，当日序号 0..4 |
| tech_name | TEXT | NOT NULL |
| tech_content | TEXT | NOT NULL |
| innovation | TEXT | NOT NULL |
| scenarios | TEXT | NOT NULL，JSON 数组字符串，固定 3 元素 |
| publish_date | TEXT | 可为空 |
| ref_link | TEXT | 可为空 |

约束：`UNIQUE(date, seq)`

### 4.5 `rating`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| user_id | INTEGER | NOT NULL，FK users.id |
| date | TEXT | NOT NULL，评分所属日期 |
| score | INTEGER | NOT NULL，1..5 |
| created_at | TEXT | NOT NULL |

约束：`UNIQUE(user_id, date)` — 同一用户同一天重复评分执行 **UPDATE**，不新增行。

### 4.6 `verify_code`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| email | TEXT | NOT NULL |
| code | TEXT | NOT NULL，4 位数字 |
| purpose | TEXT | NOT NULL，`register` / `login` |
| expire_at | TEXT | NOT NULL |
| used | INTEGER | NOT NULL DEFAULT 0 |
| created_at | TEXT | NOT NULL |

### 4.7 `eval_set`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| date | TEXT | NOT NULL |
| prompt | TEXT | NOT NULL |
| created_at | TEXT | NOT NULL |

约束：同一 `date` 只回填一次（写入前查重）。

### 4.8 `admin_audit`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| id | INTEGER | PK |
| admin_id | INTEGER | NOT NULL |
| action | TEXT | NOT NULL，见 §7.4 |
| target | TEXT | 操作对象描述 |
| created_at | TEXT | NOT NULL |

---

## 5. 采集核心逻辑

### 5.1 Prompt 模板（`collector.py` 常量）

```python
PROMPT_TEMPLATE = """请爬 {date} 的 AI 前沿技术，要求有创新或者性能相较以前有明显提升，若性能提升或创新性不足，甚至可以不用列出，列出的技术个数最多不超过 {max_items} 个，无则 return 无，参考以下网站：
{sites}

给出技术名字，这个技术大概是干嘛的（从应用的角度），这个技术相比于以前的技术创新 or 性能明显提高在哪里，可能能应用的场景（列 3 个），发布时间，参考链接。
示例，你仅能返回这样的格式：
【技术名】StableDiffusionv2.1
【技术内容】输入条件（例如文本），输出符合条件的图像
【技术创新】让图像生成性能大增
【应用场景】海报制作、图像超分、图像修复
【发布时间】2022年9月10日
【参考链接】xxxx
"""
```

`{sites}` = `source_sites` 中 `enabled=1` 的 URL，每行一个。
`{date}` = 目标日期 `YYYY-MM-DD`（Prompt 中用 `YYYY年M月D日` 格式亦可，二者择一，全项目统一）。

### 5.2 DeepSeek 调用（`deepseek.py`）

**采用 Anthropic 兼容端点**（依据见本节末尾「实测结论」，已按 §13 要求同步更新本 Spec 与 PRD §4 / 附录B）。

```python
POST {DEEPSEEK_BASE_URL}/anthropic/v1/messages
Headers:
  x-api-key: {DEEPSEEK_API_KEY}          # 注意：不是 Authorization: Bearer
  anthropic-version: 2023-06-01          # 官方标注 Ignored，保留仅作兼容
  Content-Type: application/json
Body:
{
  "model": "{DEEPSEEK_MODEL}",           # deepseek-flash
  "max_tokens": {DEEPSEEK_MAX_TOKENS},   # Anthropic 消息格式必填
  "messages": [{"role": "user", "content": "{prompt}"}],
  "tools": [{"type": "web_search_20250305", "name": "web_search",
             "max_uses": {DEEPSEEK_SEARCH_MAX_USES}}]
}
```

**响应结构**：`content` 为数组，按顺序可能同时含多种类型。

| `content[].type` | 含义 | 处理 |
| --- | --- | --- |
| `thinking` | 思维链 | **跳过**，不入正文 |
| `text` | 正文文本（取 `.text`） | **按数组顺序拼接**，即 `parser.py` 的输入 |
| `server_tool_use` | 服务端发起的搜索，`.input.query` 为查询词 | 联网判定与计数用 |
| `web_search_tool_result` | 搜索结果（含 `title` / `url`） | 证明联网成功；不入正文 |

**成功判定**：`content` 中**同时存在** `server_tool_use`（且 `name == "web_search"`）**与** `web_search_tool_result`，且拼接出的 `text` 非空。缺少任一 → 视为未联网，按 `failed` 处理并重试（防 thinking 模式下模型只"描述"调用而不真执行）。

> 作用与旧版的 `web_search_call` 判定等价，仅字段名随端点变更。

**超时与重试**：单次 `DEEPSEEK_TIMEOUT=30` 秒；失败重试 `DEEPSEEK_MAX_RETRY=2` 次，每次间隔 2 秒，即最多 3 次尝试。全部失败 → `status=failed`。

失败时**必须保留最后一次拿到的原始响应**（存在 `daily_run.raw_response`，错误描述在前、原始返回附后）。丢弃原始返回会让失败日只剩一句笼统描述，事后无法判断模型到底返回了什么。

**成本记账**：该端点**按 token 计费，无按次搜索费**。写入 `daily_run.cost_cny`：

```
cost_cny = (usage.input_tokens × IN_PRICE + usage.output_tokens × OUT_PRICE) / 1e6 × USD_CNY
```

单价取 `deepseek-flash` 闲时价 `IN_PRICE = $0.15/1M`、`OUT_PRICE = $0.6/1M`；峰时（UTC 周一至周五 01:00–04:00、06:00–10:00）翻倍。`USD_CNY` 为 `config.py` 常量。`usage.server_tool_use.web_search_requests` 仅作观测记录，**不参与计价**。

**实测结论（2026-09-28 实网探测，`deepseek-flash`）**

| 探测 | 结果 |
| --- | --- |
| `POST /responses` + `tools:[{"type":"web_search"}]` | `200`，`output` 仅 `['reasoning','message']`，**无任何搜索项**；`input_tokens` 仅 **56** → 搜索被静默忽略（官方文档将 `web_search` 等内置工具标注为「忽略」，且不符参数不报错） |
| `POST /anthropic/v1/messages` + `web_search_20250305` | `200`，`content` 含 2× `server_tool_use` + 2× `web_search_tool_result`，返回真实结果（含 title/url）；`input_tokens` **17521** |

单次采集实测 **17521 input + 1235 output ≈ ¥0.024（闲时）/ ¥0.048（峰时）**。

### 5.3 结构化解析（`parser.py`）

输入：§5.2 从 `content` 中拼接出的 `text` 全文（**不含** `thinking` / `server_tool_use` / `web_search_tool_result`）。输出：`(status, items[])`。

```
1. 若全文去空白后匹配「无」/「none」/「没有」且不含「【技术名】」→ status='empty', items=[]
2. 按「【技术名】」切分为 N 段，丢弃首段前的杂讯
3. 每段依次提取六个标记：【技术内容】【技术创新】【应用场景】【发布时间】【参考链接】
   - 取值 = 标记后到下一个「【」标记前的文本，strip 首尾空白与换行
   - 【应用场景】按 、或 ，或 , 切分；不足 3 个则用原文整体作为 1 个元素；多于 3 个截取前 3 个
4. 任一必需字段（技术名/技术内容/技术创新）为空 → 丢弃该条，计入 parse_failed_count
5. items 为空且 parse_failed_count > 0 → status='parse_failed'
6. items 非空 → status='success'，最多保留前 5 条（seq 0..4）
```

**无论何种结果，原始返回全文必须写入 `daily_run.raw_response`。**

### 5.4 采集编排（`collector.py`）

```python
def collect(date: str, force: bool = False) -> DailyRun:
    run = db.query(DailyRun).filter_by(date=date).first()

    # 幂等：非强制刷新时，已有终态记录直接返回
    if run and not force and run.status in ("success", "empty"):
        return run

    # 成本护栏（§8）
    if daily_cost() >= COST_DAILY_LIMIT_CNY:
        return degrade(date)   # 见 §5.5

    sites = enabled_sites()
    prompt = PROMPT_TEMPLATE.format(...)
    raw = deepseek_call(prompt)          # 含重试
    status, items = parse(raw)

    upsert daily_run(date, status, prompt, raw, items, cost)
    if status == "success":
        delete daily_tech where date=date   # 重采时先清旧条目
        insert daily_tech rows (seq 0..N-1)
    return run
```

**幂等性要求**：`POST /api/admin/collect` 与用户端自动补采，对同一日期重复调用**不得**产生重复条目、不得重复计费。`daily_run.date` 唯一索引是最终防线。

### 5.5 降级路径（成本超限时）

当 `daily_cost() >= COST_DAILY_LIMIT_CNY`：

1. 改用**不带** `tools` 的普通调用（模型凭已有知识输出）
2. 结果仍解析入库，但 `daily_run.status = 'success'` 且**每条 `tech_name` 追加后缀** `（未经联网核验）`
3. 写 `admin_audit(action='cost_limit_degrade')`

---

## 6. API 契约

统一前缀 `/api`。除 `/api/auth/*` 外**全部需要登录**，未登录返回 `401`。

会话：登录成功下发 `Set-Cookie: session=<签名token>; HttpOnly; SameSite=Lax; Path=/`。token = `base64(user_id.expiry)` + HMAC 签名，用 `SESSION_SECRET` 校验。

### 6.1 鉴权 `/api/auth`

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/send-code` | `{email, purpose}` | `204` / `429`（间隔不足 2 分钟） |
| POST | `/register` | `{email, code, password}` | `201 {email, role}` |
| POST | `/login` | `{email, password}` | `200 {email, role}` + Cookie |
| POST | `/login-code` | `{email, code}` | `200 {email, role}` + Cookie |
| POST | `/logout` | — | `204`，清 Cookie |
| GET | `/me` | — | `200 {email, role}` / `401` |

**`send-code` 规则**
- `purpose=register`：邮箱已存在 → `409`
- `purpose=login`：邮箱不存在 → `404`（防用户困惑；可接受枚举风险，见 §10）
- 同邮箱 2 分钟内已有发送记录 → `429`
- 生成 4 位数字验证码（`secrets.randbelow(10000)` 补零），`expire_at = now + 600s`
- 邮件：主题 `AIOneWeek验证码`，正文 `您的验证码为：{code}`，发件人 `frostyj@qq.com`
- SMTP 失败 → `502`，**不落库该验证码**

**`register` 规则**
1. 密码格式校验：`^[A-Za-z0-9]{2,8}$`，否则 `400`
2. 邮箱查重 → `409`
3. 取该邮箱最新一条 `purpose=register` 且 `used=0` 且未过期的记录，校验 `code` → 不符 `400`
4. 校验通过：`password_enc = Fernet.encrypt(password)`，建用户，标记验证码 `used=1`
5. 注册成功**不自动登录**，前端跳回登录态

### 6.2 当周查询 `/api/weekly`

`GET /api/weekly` → `200`

```json
{
  "range": {"from": "2026-09-22", "to": "2026-09-28"},
  "days": [
    {
      "date": "2026-09-28",
      "status": "success",
      "items": [
        {
          "tech_name": "...", "tech_content": "...", "innovation": "...",
          "scenarios": ["...", "...", "..."],
          "publish_date": "...", "ref_link": "..."
        }
      ]
    },
    { "date": "2026-09-27", "status": "empty", "items": [] }
  ],
  "collected_now": ["2026-09-25"]
}
```

**处理流程**

```
1. dates = [today - i for i in range(WEEK_WINDOW_DAYS)]   # 当天 + 前 6 天，共 7 天
2. missing = [d for d in dates if needs_collect(daily_run[d])]   # 缺口判定见下
3. for d in missing（严格串行，不可并发）:
       collect(d)
       collected_now.append(d)
4. 重新查询 7 天的 daily_run + daily_tech，按日期倒序返回
5. 登录用户 call_count += 1
```

**缺口判定 `needs_collect(run)`**

| 该日 run 状态 | 是否需要采集 |
|---|---|
| 无记录 | 是 |
| `success` / `empty` | 否，属终态 |
| `failed` | 是，但 `updated_at` 距今不足 **600 秒**（冷却）时跳过 |
| `parse_failed` | 否，交管理员修正（§7.2） |

- **无缺口时不得调用 DeepSeek API**，仅查库
- `status='empty'` 视为**已有数据**，不触发重采
- `failed` **会被自动重采**：模型偶尔不触发联网搜索（尤其对"未来日期"会凭自身知识作答），隔一段时间重试通常能成功。没有这条，用户会永远卡在「该日采集失败」上，只能等管理员手动重采
- 冷却 600 秒防止用户反复点「查看当周」时重复失败与长时间等待；管理员在管理页手动采集**不受冷却限制**（可显式指定日期 + 强制刷新）
- 含补采时接口耗时上界约 7 × (30s × 3 次尝试) ≈ 630s，实测单日约 19s。**前端必须显示 loading 与实时进度提示**（不能用静态文案，否则用户会以为卡死）

### 6.3 评分 `/api/rating`

`POST /api/rating` 请求 `{date, score}`，`score` ∈ 1..5 → `201`

- 同一 `(user_id, date)` 已存在 → UPDATE `score`
- 写入后立即执行 §7 评测集回填检查（同事务外，失败不影响评分返回）

### 6.4 管理端 `/api/admin`

**全部接口前置校验 `role='admin'`，否则 `403`。**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/sites` | 列出全部网站 |
| POST | `/sites` | `{url}`，URL 查重 `409` |
| PUT | `/sites/{id}` | `{url?, enabled?}` |
| DELETE | `/sites/{id}` | 删除 |
| POST | `/collect` | `{date, force?}` → `{status, item_count, cost_cny}` |
| GET | `/daily` | `?from=&to=` → 每日 run 列表 |
| GET | `/users` | 见下 |
| GET | `/users/{id}/password` | 解密返回明文，**必须写审计日志** |
| GET | `/eval-set` | 列出评测集（只读） |

`GET /api/admin/users` → `200`

```json
[{
  "id": 1, "email": "a@b.com", "role": "user",
  "password_masked": "●●●●●●",
  "call_count": 12,
  "avg_score": 4.2,
  "rating_count": 5,
  "created_at": "..."
}]
```

**密码字段规则**：列表接口**只返回掩码**。明文仅在显式调用 `GET /users/{id}/password` 时返回，且每次调用写 `admin_audit(action='decrypt_password', target=email)`。

`avg_score = Σ(score) / COUNT(*)`，无评分时为 `null`。

---

## 7. 前端

### 7.1 用户端 `index.html`

**首屏**（未鉴权）：居中标题 `AIOneWeek` + 副标题 + 主按钮「查看当周内 AI 前沿技术」。

**点击主按钮** → `GET /api/weekly`
- `401` → 弹**登录弹窗**（`<dialog>` 或遮罩层），页面不跳转
- `200` → 渲染结果区

**登录弹窗**（PRD 要求：邮箱-密码为主，下方附验证码登录 + 注册）

```
[邮箱]  [密码]           ← 主表单
[登录]
──────── 或 ────────
[验证码登录]  [注册账号]   ← 两个次要入口，切换弹窗内部视图
```

| 视图 | 字段 | 提交 |
| --- | --- | --- |
| 登录 | 邮箱、密码 | `POST /login` |
| 验证码登录 | 邮箱、[发送验证码]、验证码 | `POST /send-code(purpose=login)` → `POST /login-code` |
| 注册 | 邮箱、[发送验证码]、验证码、密码 | `POST /send-code(purpose=register)` → `POST /register` |

发送验证码按钮点击后进入 **120 秒倒计时禁用**，文案 `重新发送(118s)`。

**结果区**：按日期倒序分组的卡片列表。

```
2026-09-28
┌────────────────────────────────────────┐
│ StableDiffusion v2.1                    │
│ 技术内容：输入文本，输出符合条件的图像      │
│ 技术创新：让图像生成性能大增               │
│ 应用场景：海报制作 · 图像超分 · 图像修复    │
│ 发布时间：2022-09-10   参考链接 ↗          │
└────────────────────────────────────────┘
```

`status='empty'` 的日期渲染为灰底单行：`2026-09-27 · 这日无前沿 AI 技术`
`status='failed'` / `'parse_failed'` 渲染为警示样式行。

所有卡片底部统一脚注：**「AI 生成，请核验参考链接」**（PRD 第 10 节要求）。

**评分条**（结果区最底部，仅当次查询有 ≥1 条 `success` 时显示）

```
您对本次获取满意吗？   [1] [2] [3] [4] [5]
```

**5 秒防抖规则（PRD 硬性要求）**

```js
let pending = null;
function pick(score) {
  pending = score;
  clearTimeout(timer);
  timer = setTimeout(() => {
    fetch('/api/rating', {method:'POST', body: JSON.stringify({date: today, score: pending})});
    pending = null;
  }, 5000);
}
```

- 5 秒内再次点击 → 清除上一个定时器，重新计时
- 上传成功后按钮置为已选态，文案 `感谢反馈`
- 已评分用户当次会话内不再重复弹出评分条

### 7.2 管理员端 `admin.html`

顶部 Tab 切换两个视图（PRD 要求管理员有「主界面」+「数据管理界面」）：

- **主界面**：与用户端一致（含当周查询），额外多出「获取 &lt;日期&gt; 的 AI 前沿技术」按钮 + 日期选择器 + 「强制刷新」勾选框
- **数据管理界面**，上下两个横块（PRD 原话「可以下滑，毕竟还要有另一个横块」）：
  1. **用户表**：邮箱 / 密码（掩码 + 「查看」按钮）/ 调用次数 / 平均打分
  2. **网站列表管理**：URL 列表 + 增删改 + 启用开关

`run.py` 启动时按 `ADMIN_EMAIL` 播种管理员账号（不存在则用 `ADMIN_INIT_PASSWORD` 创建，`role='admin'`）。管理员账号**不开放注册入口**。

---

## 8. 定时任务

`app/scheduler.py`，随 FastAPI 启动（`@app.on_event("startup")` 或 lifespan），**不使用**系统 cron / Windows 计划任务。

```python
scheduler.add_job(
    job_daily_collect,
    CronTrigger(hour=8, minute=50),
    id="daily_collect",
    misfire_grace_time=3600,
    coalesce=True,
)
```

`job_daily_collect()` 对**当天日期**执行一次 `collect(today)`，异常必须捕获并写日志，**不得**让调度器崩溃。

服务重启期间错过的任务不自动补跑，依赖用户端 §6.2 的补采兜底。

---

## 9. 成本护栏

- `daily_cost()` = 当日所有 `daily_run.cost_cny` 之和
- `>= COST_DAILY_LIMIT_CNY`（默认 **¥2.0**）→ 触发 §5.5 降级
- 降级仅影响当日后续采集，次日 00:00 自动恢复
- `admin_audit` 记录每次降级触发

**阈值依据**：实测单次采集 ≈ ¥0.024（闲时）/ ¥0.048（峰时），按 token 计费（§5.2）。最坏情况（冷启动一次补满 7 天且全落峰时）≈ **¥0.34**。默认 ¥2.0 使本护栏回到「异常兜底」语义，而非每日必然触发的限流；如需收紧可下调至 ¥0.5，仍可覆盖 7 天补采。

---

## 10. 安全与合规实施项

| 项 | 要求 |
| --- | --- |
| 密码存储 | Fernet 对称加密（AES-128-CBC + HMAC）。**禁止明文入库** |
| 密钥管理 | `FERNET_KEY` 仅存于 `.env`，与数据库文件分离；`.env` 入 `.gitignore` |
| 明文密码访问 | 仅 `GET /api/admin/users/{id}/password` 返回，每次都写审计日志 |
| 审计 | `admin_audit` 记录：`collect` / `force_refresh` / `site_create` / `site_update` / `site_delete` / `decrypt_password` / `cost_limit_degrade` |
| 会话 | HttpOnly Cookie，签名校验，有效期 7 天 |
| 已知残余风险 | 可逆加密意味着 `FERNET_KEY` 泄露即全量明文泄露。缓解：密钥不入库、不入 git、解密留痕。**此风险须在 PRD 第 10 节保持披露** |
| 已知残余风险 | `send-code` 的 `purpose=login` 会暴露邮箱是否已注册。MVP 接受，上线前需评估 |
| 数据保留 | v1 不实现自动删除，保留期 10 年的删除机制留待后续迭代 |

---

## 11. 验收标准

全部须实测通过。

**A. 鉴权**
1. 未登录点主按钮 → 出登录弹窗，页面不跳转
2. 注册：邮箱收码 → 5 分钟内提交成功；验证码错误 → `400` 且不建用户
3. 同邮箱二次注册 → `409`
4. 2 分钟内重复点发送 → `429`，前端倒计时正确
5. 密码 `abc`（<2 位）或 `abc!@#`（含符号）→ `400`
6. 密码登录、验证码登录均可进入

**B. 采集与展示**
7. 管理员点「获取 &lt;日期&gt;」→ `daily_run` 新增记录，`status` ∈ 四态之一
8. 同日期再点一次（未勾强制刷新）→ **不产生第二次 API 调用**，无重复条目
9. 勾选强制刷新 → 重新调用，旧条目被清除后重建，`seq` 无重复
10. 模型返回「无」→ `status='empty'`，前端显示「这日无前沿 AI 技术」（**不是**空白或报错）
11. 新用户点击当周按钮 → 7 天数据被补齐，返回 `collected_now` 非空
12. 数据齐全后再次点击 → **响应时间 < 1 秒**，且无 DeepSeek API 调用（可用日志验证）

**C. 评分与回流**
13. 点 3 分后 5 秒内改点 5 分 → 只上传一次，值为 5
14. 同用户同日再次评分 → `rating` 表**行数不变**，score 被 UPDATE
15. `GET /api/admin/users` 返回掩码密码、正确 `call_count`、正确 `avg_score`
16. 点「查看」拿到明文，且 `admin_audit` 新增 `decrypt_password` 记录

**D. 失败路径**
17. 断网后触发采集 → `status='failed'`，前端显示失败提示，不白屏
18. 构造非法返回（如纯乱码）→ `status='parse_failed'`，`raw_response` 有内容
19. 模拟当日成本超限 → 降级路径生效，条目带「（未经联网核验）」后缀
20. 邮件 SMTP 配错 → 接口返回 `502`，前端提示，验证码未落库

**E. 工程**
21. 仓库中 `git grep` 搜不到任何 key / 授权码 / 密码字面量
22. `.env` 与 `data/` 均被 git 忽略
23. `python run.py` 冷启动无报错，`init_db()` 建表 + 播种站点 + 播种管理员

---

## 12. 明确不做

- 移动端 / 响应式适配
- 全文搜索、分类筛选、订阅、推送、收藏
- 用户端条目的人工编辑与审核
- 红队测试（无用户自由输入，prompt 由管理员控制）
- 云部署、HTTPS、域名、反向代理
- 数据自动删除机制
- 埋点（PRD 第 8 节已明确不设）

---

## 13. 实施前待办

| # | 事项 | 阻塞级别 |
| --- | --- | --- |
| 1 | **吊销并重新生成 DeepSeek API key**（旧 key 已在对话中明文泄露） | 🔴 必须 |
| 2 | ~~核对模型字符串~~ ✅ **已核实**：应为 `deepseek-flash`（`deepseek-v4-flash` 已退役，请求会被转发到 V4.1-Flash 并按 Flash 计价） | ✅ 已解决 |
| 3 | ~~核对 `/responses` 端点~~ ✅ **已核实并改道**：`/responses` 的内置工具被官方标注「忽略」，`web_search` 静默失效；已改用 Anthropic 兼容端点，见 §5.2 实测结论 | ✅ 已解决 |
| 4 | QQ 邮箱 SMTP 授权码（非登录密码） | ✅ 已提供 |
| 5 | 生成 `FERNET_KEY` 与 `SESSION_SECRET` | ✅ 已提供 |
| 6 | 若第 1 项的 key 在实现期间再次于对话/日志中暴露，交付后需再轮换一次 | 🟡 交付前 |
