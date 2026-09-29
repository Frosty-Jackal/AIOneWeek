# AIOneWeek Spec 2 — 可实施规格（增量修订）

对应 `Docs/PRD.md` v1.0 / `Docs/Spec1.md` · 2026-09-29
形态：在 Spec1 已交付的代码上做增量修订 · 技术栈不变 · 无新增运行时依赖

---

## 0. 本 Spec 的边界

**包含**：8 项修订（用户提出），涉及 prompt、解析清洗、前端文案、鉴权时序、UI 主题、历史数据迁移。

**不含**：Spec1 §12「明确不做」清单继续全部有效。

**交付定义**：8 项全部可在浏览器与代码中验证（见 §10），且历史数据的脏参考链接已清洗完毕。

**与 Spec1 的关系**：Spec1 除被本 Spec 显式修订的条款外，全部继续有效。修订对照见 §1。

---

## 1. 修订总览

| # | 诉求 | 类型 | 涉及文件 | 章节 |
| --- | --- | --- | --- | --- |
| 1 | prompt 追加约束句 | 后端 prompt | `app/collector.py` | §2 |
| 2 | 用户端不展示「本次补采 N 天」 | 前端文案 | `static/app.js` | §3 |
| 3 | 「查看」→「查看密码」 | 前端文案 | `static/app.js` | §4 |
| 4 | 全面美化：金 + 白（**白金**，非黑金） | 样式 | `static/style.css` + 两个 html | §5 |
| 5 | 登录界面底部加客服邮箱 | 前端 | `static/index.html`、`static/admin.html` | §6 |
| 6 | 等待文案改写 | 前端文案 | `static/app.js` | §7 |
| 7 | 未登录不得进入等待态 | 前端时序（**Bug**） | `static/app.js` | §8 |
| 8 | 参考链接格式修正 | prompt + 解析 + 前端 + 数据迁移 | `collector.py`、`parser.py`、`app.js`、新迁移脚本 | §9 |

本 Spec 修订的 Spec1 条款：

| Spec1 位置 | 原内容 | 修订 |
| --- | --- | --- |
| §5.1 `PROMPT_TEMPLATE` | 模板结尾于「【参考链接】xxxx」 | §2 追加两段约束 |
| §5.3 `parse()` 签名 | `parse(raw_text, max_items)` | §9.3 增可选参数 `sites` |
| §7.1 等待文案 | 含「（首次需逐日补采，约每天 20 秒）」 | §7 删除并改写 |
| §7.1 点击主按钮流程 | 先起计时器、后判登录 | §8 调换顺序 |
| §7.2 管理端「查看」按钮 | 文案「查看」 | §4 改「查看密码」 |
| §（样式）整体配色 | 蓝色系（`--brand: #2f6df6`） | §5 全量替换为金白令牌 |

---

## 2. 改动 1 — Prompt 追加约束

### 2.1 用户原文（逐字追加，不得改写）

在 `PROMPT_TEMPLATE` 末尾「【参考链接】xxxx」之后追加：

```
仅能为今天日期发布的，若不是，请不要返回给我！而且只要技术/模型，不要学术方法，参考链接格式需规范url
```

改后模板（现状见 `app/collector.py:23-34`）：

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
仅能为今天日期发布的，若不是，请不要返回给我！而且只要技术/模型，不要学术方法，参考链接格式需规范url
"""
```

### 2.2 「今天日期」按原文保留

`{date}` 已在 prompt 首行出现，模型能对应上，所以**不改写为用户原文之外的形式**。

若实测发现模型不遵守该句（例如仍返回前几天发布的），可把它替换为 `{date}`，即 `仅能为{date}发布的，若不是，请不要返回给我！`。这是一处可随时切换的等价改写，**不改变语义**，回退成本为零。

### 2.3 ⚠️ 「只要技术/模型，不要学术方法」的连带影响 —— 落地前必读

Spec1 播种的唯一来源站是 `https://huggingface.co/papers/trending` —— 这是**论文**趋势榜，与「不要学术方法」直接冲突。

现有数据佐证：`2026-09-26` 的 5 条里 4 条是论文方法（`Agent-Editing World Model`、`Harness-Zero`、`Co-Evolving Harnesses and Models`、`State-Grounded Conditioning`），只有 1 条算模型；`2026-09-27` 的 5 条（`MemBodied`、`Verifiable Hidden Dynamics Play`、`Rufus-Air`、`Qwen-Planner-Agent`、`PackLab`）同样偏方法侧。

加上新约束后，这类日子大概率整体返回「无」→ `status='empty'`。

**后果**：用户端会出现较多「这日无前沿 AI 技术」灰行。PRD §1 的反指标与 §9 回滚条件都不含 empty 率，所以**不会**触发回滚，但体验会变差。

**建议**（不属强制项，由管理员在管理端「网站列表」自行添加）：

- `https://huggingface.co/models?sort=trending` —— 模型趋势榜，与新约束同向
- 各厂商发布页，如 `https://openai.com/news/`、`https://www.anthropic.com/news`

**验收时要观察**：修订后连续 3 天的 `empty` 占比。若 > 40%，说明来源站需要换成模型向。

### 2.4 验收

- `git grep "仅能为今天日期发布的"` 命中 `app/collector.py`
- 管理端对任一新日期强制刷新 → 查 `daily_run.prompt`，字段以该句结尾

---

## 3. 改动 2 — 用户端不展示「本次补采 N 天」

### 3.1 现状

`static/app.js:376`：

```js
const extra = data.collected_now?.length ? `，本次补采 ${data.collected_now.length} 天` : "";
```

`static/app.js:379`：

```js
setStatus(`已展示 ${range}${extra}${warn}`, failed ? "" : "good");
```

用户看到的是：`已展示 2026-09-23 ~ 2026-09-29，本次补采 1 天`

### 3.2 改后

普通用户端（`PAGE === "index"`）**不拼接** `extra`；管理端主界面（`PAGE === "admin"`）**保留**。

**理由**：用户原话是「**普通用户端**不用展示」—— 措辞明确排除了管理端。补采天数对管理员有意义（是判断「今天是不是首采」的依据），对普通用户是纯噪音。

```js
// 补采天数只对管理员有意义：普通用户只关心「看到什么」，不关心后台采了几次
const extra =
  PAGE === "admin" && data.collected_now?.length
    ? `，本次补采 ${data.collected_now.length} 天`
    : "";
setStatus(`已展示 ${range}${extra}${warn}`, failed ? "" : "good");
```

> **需用户确认**：若希望两端都不展示，把 `PAGE === "admin" &&` 删掉即可。这是一行改动，见 §11 待确认项 4。

### 3.3 API 契约不变

`GET /api/weekly` 继续返回 `collected_now` 数组（`app/routers/weekly.py` 末尾）。**仅前端不渲染**，后端不动。

### 3.4 验收

- 用户端无缺口时，状态行严格等于 `已展示 2026-09-23 ~ 2026-09-29`
- 用户端有缺口时，状态行为 `已展示 <from> ~ <to>`，**不含**「本次补采」
- 管理端主界面仍能看到「，本次补采 N 天」
- 抓包确认响应体仍含 `collected_now` 字段

---

## 4. 改动 3 — 「查看」按钮改为「查看密码」

`static/app.js:427`：

```js
const btn = el("button", "ghost", "查看");
```

→

```js
const btn = el("button", "ghost", "查看密码");
```

配套一处修正：该按钮所在的 `<td>` 需加 `ops` class。

`loadUsers()` 里操作列是裸的 `const ops = el("td");`（`app.js:426`），而 `loadSites()` 用的是 `el("td", "ops")`（`app.js:475`）。`.ops` 带 `white-space: nowrap`（`style.css:262`）。文案从 2 字变 4 字后，窄列里会折行，所以：

```js
const ops = el("td", "ops");
```

表头 `<th>密码</th>` 保持不动 —— 按钮文案已自带说明。

### 验收

- 管理端「数据管理界面 → 用户」表格最后一列按钮显示「查看密码」，且不折行
- 点击仍解密返回明文，`admin_audit` 新增 `decrypt_password` 记录（Spec1 §6.4 不变）

---

## 5. 改动 4 — 金白主题（白金，非黑金）

### 5.1 设计原则（三条硬约束）

1. **白金而非黑金**：底色是**暖白/近白**，金色只做点缀（品牌名、按钮、标签、细描边、星星）。**任何大面积深色背景一律不用。**
2. **背景不抢内容**：纯色 + 极淡金色细节（1px 金线、卡片轻描边）。**禁止**渐变铺底、纹理图、大面积金色色块、光晕/发光、动态背景。
3. **金色不得承载正文**：亮金（`#D4AF37` 一类）在白底上对比度仅约 1.9:1，用在文字上不可读。所有正文级金色必须用 §5.2 的 `--gold` 或 `--gold-deep`。

### 5.2 设计令牌（`static/style.css` 的 `:root` 全量替换）

Spec1 的 `--brand` / `--brand-ink` / 冷灰 `--line` 全部废弃。

```css
:root {
  /* 底色：暖白。带一丝米色，比纯白柔和，且与金色同色温 */
  --bg:        #FBFAF6;
  --bg-soft:   #F5F1E8;   /* 次级面：页签底、表头 */
  --panel:     #FFFFFF;

  /* 文字：暖黑系，不用纯黑 */
  --ink:       #23211C;
  --ink-2:     #6E6659;
  --ink-3:     #797263;   /* 脚注、次要说明 */

  /* 描边：暖灰金，替换 Spec1 的冷灰 */
  --line:      #EBE5D8;
  --line-2:    #DFD6C2;

  /* 金 —— 三级各有专属用途，不得混用 */
  --gold:      #8C6B1F;   /* 正文级：链接、按钮底。白底 4.95:1 */
  --gold-deep: #6E5314;   /* 小字金 / hover / active。白底 7.2:1 */
  --gold-line: #C9A227;   /* 装饰级：1px 金线、竖条、星星。不承载文字 */
  --gold-soft: #F6EFDD;   /* 金色浅底：标签、药丸、选中态 */
  --gold-ink:  #FFFFFF;   /* 金底上的文字 */

  /* 语义色：按暖白底重新取值，避免冷色突兀 */
  --ok:        #1F7A4D;
  --warn:      #9A6B12;
  --bad:       #B23A3A;

  --radius:    10px;
  --radius-lg: 14px;
  --shadow:    0 1px 2px rgba(60,48,20,.05), 0 8px 24px rgba(60,48,20,.06);
}
```

### 5.3 对比度账（硬性验收项）

已按 WCAG 2.1 相对亮度公式逐一核算。**实现后须用 DevTools 或对比度检查器复核。**

| 前景 | 背景 | 对比度 | 门槛 | 结论 |
| --- | --- | --- | --- | --- |
| `--gold` #8C6B1F | #FFFFFF | 4.95:1 | 4.5:1 | ✅ 正文可用 |
| `--gold-deep` #6E5314 | #FFFFFF | 7.21:1 | 4.5:1 | ✅ |
| `--gold-deep` #6E5314 | `--gold-soft` #F6EFDD | 6.29:1 | 4.5:1 | ✅ 小字金必须用这个组合 |
| `--gold` #8C6B1F | `--gold-soft` #F6EFDD | 4.32:1 | 4.5:1 | ❌ **不达标，禁用于 12px 标签** |
| `--gold-ink` #FFFFFF | `--gold` 按钮底 | 4.95:1 | 4.5:1 | ✅ |
| `--ink` #23211C | `--bg` #FBFAF6 | 15.4:1 | 4.5:1 | ✅ |
| `--ink-2` #6E6659 | `--panel` #FFFFFF | 5.66:1 | 4.5:1 | ✅ |
| `--ink-2` #6E6659 | `--bg-soft` #F5F1E8 | 5.02:1 | 4.5:1 | ✅ 表头可用 |
| `--ink-3` #797263 | #FFFFFF | 4.77:1 | 4.5:1 | ✅ 脚注可用 |
| `--ok` #1F7A4D | #FFFFFF | 5.32:1 | 4.5:1 | ✅ |
| `--warn` #9A6B12 | #FFFFFF | 4.68:1 | 4.5:1 | ✅ |
| `--bad` #B23A3A | #FFFFFF | 5.90:1 | 4.5:1 | ✅ |
| ✗ #D4AF37（亮金） | #FFFFFF | ≈1.9:1 | 4.5:1 | ❌ **禁止用于任何文字** |

两条最容易踩的坑：

- **金色浅底上的小字必须用 `--gold-deep`，不能用 `--gold`** —— 4.32:1 不达标，而 `.field .label` 是 12px。
- **`--ink-3` 已调到 4.77:1 而不是更浅的灰** —— 页脚那句「所有条目均为 AI 生成，请核验参考链接」是 PRD §10 的合规声明，属重要内容，不能用不达标的浅灰敷衍。

### 5.4 逐组件改法

| 组件 | 选择器 | 改法 |
| --- | --- | --- |
| 顶栏 | `.topbar` | 白底；底边 `1px solid var(--line)`；再叠 2px 金线：`box-shadow: inset 0 -2px 0 var(--gold-line)`。**全站仅此一条金色横贯带**，其余一律留白 |
| 品牌 | `.brand` | `display:flex; align-items:center; gap:10px;` |
| 品牌 logo | `.brand img.logo` | `height: 32px; width: auto; display: block;`（见 §5.5） |
| 品牌文字 | `.brand .name` | `font-weight:700; color:var(--gold); letter-spacing:.5px;` |
| 管理端标签 | `.brand .tag` | `background:var(--gold-soft); color:var(--gold-deep); border:1px solid var(--gold-line);` 圆角 999px |
| 链接 | `.link` | `color: var(--gold);` hover 加下划线（保留） |
| 主按钮 | `button.primary` | `background:var(--gold); color:var(--gold-ink); border:1px solid var(--gold);` hover `background:var(--gold-deep)` —— **只许变深，不许变浅**（变浅会让白字跌穿 4.5:1） |
| 次要按钮 | `button.ghost` | 白底 + `1px solid var(--line-2)`；hover `border-color:var(--gold); color:var(--gold)` |
| 页签 | `.tab` / `.tab.active` | `.tab`：`color:var(--ink-2)`。`.tab.active`：`background:var(--panel); color:var(--gold); font-weight:600; border-color:var(--line); border-top:2px solid var(--gold-line)` |
| 卡片 | `.day`、`.panel`、`.rating` | 白底 + `1px solid var(--line)` + `box-shadow: var(--shadow)`；`.day` / `.panel` 圆角用 `var(--radius-lg)` |
| 日期标题 | `.day-head h3` | `color:var(--ink); border-left:3px solid var(--gold-line); padding-left:10px;` |
| 状态药丸 | `.pill` | `background:var(--gold-soft); color:var(--gold-deep); border:1px solid var(--gold-line);` |
| 药丸-语义变体 | `.pill.ok/.warn/.muted` | 保留各自语义色作文字色，背景统一 `var(--bg-soft)`，边框 `var(--line-2)` |
| 字段标签 | `.field .label` | **必须替换掉 Spec1 的蓝色 `#eef3ff`**：`background:var(--gold-soft); color:var(--gold-deep); border:1px solid var(--gold-line);` |
| 条目分隔 | `.item` | `border-top: 1px dashed var(--line-2)` |
| 参考链接 | `.meta a.ref` | `color: var(--gold)` |
| 无链接兜底 | `.meta .ref-none` | `color: var(--ink-3)`（新增，见 §9.3） |
| 评分星 | `.star` | 未选中 `#DCD5C6`；hover / `.on` 用 `var(--gold-line)` #C9A227 —— **装饰性元素，允许用亮金** |
| 表格 | `table.grid` | `th`：`background:var(--bg-soft); color:var(--ink-2);` 行分隔 `1px solid var(--line)`；`tbody tr:hover { background: var(--bg); }` |
| 弹窗 | `.dialog` | 白底 + `1px solid var(--line-2)` + `box-shadow: 0 18px 48px rgba(60,48,20,.18)`；`border-top: 3px solid var(--gold-line)`；`::backdrop { background: rgba(40,33,16,.32); }` |
| 输入框 | `input`、`.dialog input` | 白底 + `1px solid var(--line-2)`；`:focus { border-color: var(--gold); box-shadow: 0 0 0 3px var(--gold-soft); outline: none; }` —— **focus 环必须可见**（键盘可达性） |
| 弹窗分隔 | `.dialog .or` | `color: var(--ink-3)` |
| 页脚 | `.foot` | `color: var(--ink-3); border-top: 1px solid var(--line); margin-top: 40px; padding-top: 16px;` |

### 5.5 顶栏 Logo

用户已选定「顶栏放透明底 logo」。`Docs/logotransparent.png` 实测：1536×1024 RGBA，**真透明**（四角 alpha=0；alpha=0 处的非零 RGB 是未清零的垃圾值，合成后不可见），可安全用于白底。

但**不能直接引用**，有两个问题必须处理：

1. **四周有大量透明留白**：实际内容包围盒为 `x 49..1507, y 125..870`，垂直方向有 **125 + 153 = 278px（占 27%）的留白**。若不裁剪，按固定 `height` 渲染时图形只占框高约 73%，看起来偏小且垂直不居中。
2. **文件 1.7 MB**：每次页面加载拉 1.7MB 不合理。

**做法**：生成 `static/logo.png` —— 按包围盒裁掉透明留白，等比缩放到高 **128px**（裁剪后内容比例约 **1.96:1**，即约 250×128），PNG 优化压缩。`Docs/` 下的原图**保持不动**（它是母版）。

这是一次性构建动作，实现方式不限（Pillow / ImageMagick / 在线工具均可）。**不要**把 Pillow 加进 `requirements.txt` —— 运行时不需要它。

HTML（`index.html` 与 `admin.html` 的 `.brand`）：

```html
<div class="brand">
  <img class="logo" src="/static/logo.png" alt="AIOneWeek">
  <span class="name">AIOneWeek</span>
</div>
```

> **为什么 logo 旁仍要保留文字 `AIOneWeek`**：图形里的字母是「AIOW」，缩到 32px 高时已不可辨，视觉上只是一个金色徽标。品牌名仍需文字承载。`alt="AIOneWeek"` 是必需的（无障碍）。

管理端在 `.name` 之后保留原有的 `<span class="tag">管理端</span>`。

### 5.6 反例清单（评审时用来否决实现）

出现任一即不合格：

- 黑底 / 深灰底区块，或任何大面积深色背景
- 金色渐变铺满背景
- 金色发光 / 光晕 / 霓虹效果
- 正文使用亮金 `#D4AF37` 一类的浅金
- 金色浅底上的 12px 小字用了 `--gold` 而非 `--gold-deep`
- 主按钮 hover 时颜色**变浅**
- 标签 / 药丸仍残留 Spec1 的蓝色 `#eef3ff` / `#2f6df6`
- 输入框 focus 无可见焦点环
- 顶栏出现两条以上金色横贯带

### 5.7 验收

- 逐组件走查 §5.4 表格
- DevTools 复核 §5.3 对比度表，**两条坑点必须单独确认**
- 100% 与 150% 缩放均无横向滚动条
- 键盘 Tab 走一遍登录弹窗：每个输入框与按钮都有可见 focus 环
- `git grep -E "#2f6df6|#eef3ff|#f5f6f8"` 在 `static/` 下**零命中**

---

## 6. 改动 5 — 登录界面底部附客服邮箱

`static/index.html`，弹窗 `#auth-dialog` 内、`<p class="dialog-msg" id="auth-msg">` **之后**新增：

```html
<p class="dialog-foot">客服邮箱：<a href="mailto:frostyj@qq.com">frostyj@qq.com</a></p>
```

`static/admin.html` 的 `#auth-dialog` 同位置同样新增。

CSS：

```css
.dialog-foot {
  margin: 10px 0 0;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  font-size: 12px;
  color: var(--ink-2);
  text-align: center;
}
.dialog-foot a { color: var(--gold); }
```

> **位置说明**：放在三个视图（登录 / 验证码登录 / 注册）的**公共区域**。`#auth-msg` 与新增的 `.dialog-foot` 都在 `.view` 之外，`showView()` 切换视图时不会隐藏它们，所以客服邮箱在三个视图下**都常驻**。这正好符合「登录界面底下」的要求。

### 6.1 🔴 必须同步修订 PRD —— 当前文档自相矛盾

`Docs/PRD.md:166` 原文：

> **关于人工兜底**：本产品**无人工客服**，不写「转人工」。

加了客服邮箱就等于**开了人工客服入口**。Spec2 落地时必须同时修订 PRD §6 该段，否则文档与产品行为互相打脸。建议改为：

> **关于人工兜底**：本产品不提供在线人工客服，也不设「转人工」入口。所有需人工介入的场景收敛到管理员端 —— 管理员可在数据管理界面重试采集、修正解析失败条目。用户可在登录界面看到客服邮箱 `frostyj@qq.com`，但 **v1 不承诺响应时限**。

### 6.2 验收

- 登录 / 验证码登录 / 注册三个视图下，弹窗底部**都**显示 `客服邮箱：frostyj@qq.com`
- 点击触发系统邮件客户端（`mailto:`）
- 该行位于 `#auth-msg` 之下，与错误提示不重叠、不挤压

---

## 7. 改动 6 — 等待文案

### 7.1 现状

`static/app.js:356-365`：

```js
function startWaitTicker() {
  let secs = 0;
  const paint = () => setStatus(`正在获取当周数据…（首次需逐日补采，约每天 20 秒）已等待 ${secs} 秒`);
  paint();
  const id = setInterval(() => { secs += 1; paint(); }, 1000);
  return () => clearInterval(id);
}
```

### 7.2 改后

```js
/* 首次补采要逐日串行调用模型，一天约 20 秒。静态文案会让用户以为卡死，
   所以显示实时秒数。不再暴露「每天 20 秒」这个内部估算 —— 它把用户的
   注意力引向后台耗时，而用户只需要知道「还在跑、别关」。 */
function startWaitTicker() {
  let secs = 0;
  const paint = () => setStatus(`正在获取当周数据…已等待 ${secs} 秒，请耐心等待！`);
  paint();
  const id = setInterval(() => {
    secs += 1;
    paint();
  }, 1000);
  return () => clearInterval(id);
}
```

渲染结果：`正在获取当周数据…已等待 0 秒，请耐心等待！`

### 7.3 验收

- 有缺口状态下点击主按钮 → 状态行从 `已等待 0 秒，请耐心等待！` 逐秒递增
- `git grep "首次需逐日补采"` **零命中**（确认无残留文案）
- `git grep "约每天 20 秒"` **零命中**

---

## 8. 改动 7 — 未登录时不得进入等待态

### 8.1 现状（Bug）

`static/app.js:367-386`：

```js
async function loadWeekly() {
  const btn = $("#btn-weekly");
  if (btn) btn.disabled = true;
  const stopTicker = startWaitTicker();                      // ← 先启动计时器
  try {
    const data = await withAuth(() => apiJson("/api/weekly"));   // ← 后判登录
    if (!data) return;
    ...
```

`withAuth`（`app.js:90-101`）在 401 时才弹登录框，但它**晚于** `startWaitTicker()` 执行。所以未登录用户点按钮时，会先看到：

```
正在获取当周数据…（首次需逐日补采，约每天 20 秒）已等待 0 秒
```

然后才弹登录框 —— 一次**假进度**。用户会以为采集已经在跑了。

### 8.2 改后

把登录态判断**提到计时器之前**，并把 401 兜底从 `withAuth` 里拆出来（这里需要精确控制「先停计时器、再弹窗」的顺序，`withAuth` 的「弹窗后返回 `undefined`」做不到这点）：

```js
async function loadWeekly() {
  const btn = $("#btn-weekly");
  if (btn) btn.disabled = true;
  let stopTicker = null;

  // 未登录时不得进入等待态：那会让用户以为采集已经在跑，
  // 实际只是要弹登录框，属于假进度。
  const askLogin = () => {
    pendingAfterLogin = loadWeekly;
    openAuth("view-login");
  };

  try {
    if (!currentUser) {
      askLogin();          // 已知未登录：直接弹窗，计时器一次都不启动
      return;
    }

    stopTicker = startWaitTicker();
    const data = await apiJson("/api/weekly");
    renderDays(data.days);

    const range = `${data.range.from} ~ ${data.range.to}`;
    const extra =
      PAGE === "admin" && data.collected_now?.length
        ? `，本次补采 ${data.collected_now.length} 天`
        : "";
    const failed = data.days.filter((d) => d.status === "failed").length;
    const warn = failed ? `；${failed} 天采集失败，稍后重试即可自动补采` : "";
    setStatus(`已展示 ${range}${extra}${warn}`, failed ? "" : "good");
  } catch (err) {
    if (err.status === 401) {
      // 会话中途失效（例如在另一个标签页退出登录）：先停计时器，再弹窗
      stopTicker?.();
      stopTicker = null;
      askLogin();
      return;
    }
    setStatus(err.message, "bad");
  } finally {
    stopTicker?.();
    if (btn) btn.disabled = false;
  }
}
```

四个要点：

1. **零额外请求**：`currentUser` 已由 `boot()` 在页面加载时通过 `GET /api/auth/me` 填好（`app.js:576-579`），这里的判断不发网络请求。
2. **不死循环**：`askLogin()` 里 `pendingAfterLogin = loadWeekly`，登录成功后 `afterAuthOk()`（`app.js:154-161`）自动续跑。第二次进入时 `currentUser` 已有值，`!currentUser` 为假，走正常路径。
3. **401 兜底保留**：覆盖「页面打开时是登录态、点按钮前在别处退出了」的窗口期。
4. **不再用 `withAuth`**：它对 401 的处理无法先停计时器。`withAuth` 仍被 `loadUsers` / `loadSites` / `loadEvalSet` / 采集按钮使用，**不是死代码**，保留。

### 8.3 边界：管理端不受影响

`admin.html` 有同名的 `#btn-weekly`，共用 `loadWeekly`。管理员在 `boot()` 中若未登录会**立即**弹登录框（`app.js:583-593`），通常点不到这个按钮。改动后行为一致，无需额外处理。

管理端「获取该日期的 AI 前沿技术」按钮（`app.js:534-555`）用的是静态 `正在采集 ${date}…`，**不含计时器**，本次不动。

### 8.4 验收

- **未登录**（清 Cookie 或隐身窗口）点「查看当周内 AI 前沿技术」→ **立即**弹登录框，`#hero-status` **全程为空**，页面上任何时刻都不出现「正在获取当周数据」
- 弹窗内完成登录 → 登录框自动关闭并**自动续跑**当周查询（无需再点一次按钮）
- 已登录但 Cookie 失效时点按钮 → 不残留 `正在获取…` 文案（计时器被 `stopTicker?.()` 停掉），改为弹登录框
- 已登录正常路径：计时器照常从 `已等待 0 秒，请耐心等待！` 递增

---

## 9. 改动 8 — 参考链接格式

### 9.1 问题实证

查 `data/aioneek.db` 的 `daily_tech.ref_link`，脏值有四种形态：

| 形态 | 实例 | 点开的后果 |
| --- | --- | --- |
| URL + 括号注释 | `https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash （论文聚合页 https://paperswithcode.co/）` | 浏览器把空格与中文百分号转义 → **404** |
| 多条 URL 用 `；` 并列 | `https://arxiv.org/abs/2609.28256 ；项目页 https://declare-lab.github.io/MemBodied/` | 同上 → **404** |
| URL + 多行说明 | `https://huggingface.co/zai-org/GLM-5.3\n\n补充：若你需要严格锁定…` | 同上 → **404** |
| 空值 | `2026-09-26 seq 4 BiCFlow-MER` 的 `ref_link = None` | 前端整块不渲染链接 |

根因在 `static/app.js:298`：

```js
a.href = item.ref_link;   // 模型返回的原始字符串直接当 href
```

**模型的原始返回从未被清洗过。**

### 9.2 用户对格式的裁决（已确认）

1. **链接必须是该技术的具体来源页** —— arXiv abs 页、HF 模型页、官方博客原文。
   - ✅ `https://arxiv.org/abs/2609.29808v1`
   - ✅ `https://huggingface.co/zai-org/GLM-5.3`
   - ❌ `https://huggingface.co/papers/trending`（聚合榜页）
   - ❌ `https://www.sohu.com/a/1080920824`（转载新闻）
2. **拿不到有效 URL 时**：**保留整条**，链接处显示 **`暂无链接，建议上网搜索`**（不是丢弃条目）。

现有数据里 `https://huggingface.co/papers/trending` 高频出现 —— 那正是 prompt 里 `{sites}` 喂给模型的来源站 URL。模型找不到具体页面时**原样回填**了它。

### 9.3 三层修复

#### 第 1 层：Prompt（`app/collector.py`）

§2 已追加用户原文「参考链接格式需规范url」。但**这句话不足以约束模型** —— 现有脏数据正是在旧 prompt 下产生的。所以在其后再补一段明确的格式规约：

```
其中【参考链接】必须满足：
1. 只有一个 URL，形如 https://arxiv.org/abs/2609.29808 或 https://huggingface.co/zai-org/GLM-5.3
2. 不得附带括号注释、说明文字，不得用「；」并列多个链接，不得换行
3. 必须指向该技术自身的页面（论文页 / 模型页 / 官方博客原文），不得使用 HuggingFace Papers 趋势榜、Papers with Code 等聚合榜页，也不得使用转载新闻页
4. 找不到该技术的具体页面时，【参考链接】直接写：无
```

#### 第 2 层：解析清洗（`app/parser.py`）

**不信任模型**。新增纯函数：

```python
URL_RE = re.compile(r"https?://[^\s（）()【】\[\]<>\"'，。；、]+")


def _norm_for_compare(u: str) -> str:
    """比较用规范化：去 fragment/query、去尾斜杠、转小写。
    只用于比对，不得拿它覆盖入库的原始 URL —— 路径大小写可能是有意义的。"""
    return u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def is_source_site(url: str, sites: Iterable[str]) -> bool:
    """URL 是否就是把来源站原样回填（Spec2 §9.3）。"""
    return any(_norm_for_compare(url) == _norm_for_compare(s) for s in sites)


def normalize_ref_link(raw: str | None, sites: Iterable[str] = ()) -> str | None:
    """从模型返回的【参考链接】原文里提取唯一规范 URL。

    模型常见四种脏写法，全部在这里收口：
      - "https://a/b （注释文字）"      → https://a/b
      - "https://a/b ；https://c/d"     → https://a/b（取第一条）
      - "https://a/b\\n\\n补充说明…"     → https://a/b
      - 无 URL / 空值                    → None

    另外拒掉「把来源站原样回填」的偷懒写法：与 source_sites 任一条相同时
    返回 None —— 聚合榜页不是这项技术的具体来源页。

    None 不是丢弃信号：条目照常保留，由前端显示「暂无链接，建议上网搜索」。
    """
    if not raw:
        return None
    match = URL_RE.search(raw)
    if not match:
        return None
    url = match.group(0).rstrip(".,;:!?、。；：！？")   # 剥离紧贴 URL 的句末标点
    if not url or is_source_site(url, sites):
        return None
    return url
```

`parse()` 签名加一个可选参数，把来源站传进来：

```python
def parse(raw_text: str, max_items: int = 5, sites: Iterable[str] = ()) -> tuple[str, list[dict]]:
    ...
    item["ref_link"] = normalize_ref_link(item.get("ref_link"), sites)
```

`collector.py:142` 同步改为：

```python
status, items = parser.parse(result.text, settings.max_items_per_day, sites)
```

来源站**只查一次**，不要为了传参而多查库：

```python
sites = enabled_sites(db)
prompt = build_prompt(db, day, sites)          # build_prompt 改为接受 sites
...
status, items = parser.parse(result.text, settings.max_items_per_day, sites)
```

> `build_prompt` 相应改为接受 `sites` 参数（现状是内部自己调 `enabled_sites`，见 `collector.py:74-80`）。

**`ref_link` 依旧不是必需字段** —— `REQUIRED_FIELDS` 保持 `("tech_name", "tech_content", "innovation")` 不变（`parser.py:18`）。这正好落实 §9.2 裁决的第 2 条：**清洗后为 `None` 的条目照样保留**。

#### 第 3 层：前端渲染（`static/app.js`）

`renderItem()` 现在只在小 `ref_link` 为真时才渲染链接（`app.js:296-302`）。改为**两种情况都有输出**：

```js
/* 参考链接直接来自模型输出，必须校验协议：只放行 http/https，
   避免 javascript: 一类被当成可点击链接（Spec2 §9.3）。 */
function safeUrl(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw, location.origin);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch (_) {
    return null;
  }
}

// ... renderItem 内替换掉现有的 meta 拼装
const meta = el("div", "meta");
if (item.publish_date) meta.append(el("span", null, `发布时间：${item.publish_date}`));

const href = safeUrl(item.ref_link);
if (href) {
  const a = el("a", "ref", "参考链接 ↗");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  meta.append(a);
} else {
  meta.append(el("span", "ref-none", "暂无链接，建议上网搜索"));
}
```

CSS 见 §5.4 的 `.meta .ref-none` 行。

#### 第 4 层：历史数据清洗（一次性迁移）

已有 8 个日期的 `daily_tech.ref_link` 是脏的 —— **用户看到的就是这些**。新增 `scripts/clean_ref_links.py`：

**契约**

1. 读 `source_sites` **全部** URL（含 `enabled=0` 的 —— 历史条目可能引用了已停用的站点）
2. 对每行 `daily_tech` 调 `parser.normalize_ref_link(ref_link, sites)`
3. **值有变化才 `UPDATE`**；逐行打印 `旧值 → 新值`（或 `旧值 → NULL`）
4. `--dry-run` 只打印不写库
5. 结束打印统计：`扫描 N 行，清洗 M 行，其中置空 K 行`
6. **幂等**：重复执行结果一致，第二次变更行数为 0

**注意**：脚本要 `from app import parser`，请在脚本顶部做 `sys.path` 引导（或改用 `python -m scripts.clean_ref_links` 运行）。`scripts/` 需有 `__init__.py`（若走 `-m` 方式）。

**不自动删除条目**。清洗后为 NULL 的行保留，靠 §9.3 第 3 层的前端兜底文案呈现。

对现有数据执行后的预期（用当前库实测推演）：

| 原值 | 清洗后 |
| --- | --- |
| `https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash （论文聚合页 …）` | `https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash` |
| `https://arxiv.org/abs/2609.28256 ；项目页 https://…` | `https://arxiv.org/abs/2609.28256` |
| `https://huggingface.co/papers/trending （…）` | **NULL**（回填来源站） |
| `https://huggingface.co/papers/trending` | **NULL** |
| `http://arxiv.org/abs/2609.29808v1` | 不变 |
| `None` | 不变 |

> ⚠️ 清洗后会有相当一部分变成「暂无链接，建议上网搜索」—— 这是**正确**结果：那些链接本来点开就是 404 或榜单页，不是这项技术的来源。**想拿到真正可用的链接，需在管理端对这些日期勾「强制刷新」重采**（走新 prompt）。

### 9.4 验收

- `normalize_ref_link` 有单测，覆盖 §9.1 的四种形态 + 来源站回填 + 空值，共 6 例
- 新采一天（管理端勾「强制刷新」）→ 该日所有 `ref_link` 满足 `^https?://\S+$`，**不含空格与中文**
  - 验证 SQL：`SELECT date, seq, ref_link FROM daily_tech WHERE ref_link LIKE '% %' OR ref_link LIKE '%（%';` → **零行**
- 前端：有链接 → 可点、新标签打开；无链接 → 灰色 `暂无链接，建议上网搜索`、不可点
- 迁移脚本 `--dry-run` 与实跑的行数一致；实跑两次，第二次变更行数为 0
- 无效 URL / 断网不导致白屏

---

## 10. 验收总表

Spec1 §11 的 A–E 组**必须全部重跑**。本次改了 prompt 与 `parse()` 签名，**B 组（采集与展示）** 与 **D 组（失败路径）** 最易受影响，重点确认：

- Spec1 #10：模型返回「无」→ 仍正确落 `empty`，**不得**因新 prompt 的严格约束而变成 `parse_failed`
- Spec1 #18：纯乱码 → 仍 `parse_failed`，`raw_response` 有内容

新增 F 组：

| # | 验收 | 对应 |
| --- | --- | --- |
| 23 | 未登录点主按钮 → **立即**弹登录框，页面全程不出现「正在获取当周数据」 | §8 |
| 24 | 登录成功后自动续跑当周查询，无需再点按钮 | §8 |
| 25 | 等待文案为 `正在获取当周数据…已等待 N 秒，请耐心等待！`；`git grep` 搜不到旧文案 | §7 |
| 26 | 用户端状态行不含「本次补采」；管理端主界面仍含 | §3 |
| 27 | 管理端用户表按钮文案为「查看密码」且不折行；点击返回明文并新增 `decrypt_password` 审计 | §4 |
| 28 | 登录 / 验证码登录 / 注册三视图下，弹窗底部都有 `客服邮箱：frostyj@qq.com` | §6 |
| 29 | `static/` 下 `git grep -E "#2f6df6\|#eef3ff\|#f5f6f8"` 零命中；正文金色对比度 ≥ 4.5:1 | §5 |
| 30 | 顶栏显示裁剪后 logo（`height:32px`），旁有金色文字 `AIOneWeek` | §5.5 |
| 31 | 新采数据 `ref_link` 均为单一规范 URL；无链接条目显示「暂无链接，建议上网搜索」 | §9 |
| 32 | 历史数据迁移脚本运行两次，第二次 0 变更 | §9.3 |

---

## 11. 风险与待确认

| # | 事项 | 级别 |
| --- | --- | --- |
| 1 | 「只要技术/模型，不要学术方法」与唯一来源站（HF Papers 趋势榜）性质冲突，`empty` 天数预计上升。建议管理员增补模型向来源站（§2.3） | 🟡 需观察 |
| 2 | 「仅能为今天日期发布的」会进一步收紧产出。实测波动大时可把它替换为 `{date}`（§2.2），回退成本为零 | 🟡 可回退 |
| 3 | **客服邮箱与 PRD §6「本产品无人工客服」直接冲突，PRD 必须同步修订**（§6.1） | 🔴 必须 |
| 4 | 「本次补采 N 天」按「用户端不展示、管理端保留」实现。若希望两端都去掉，删一个条件即可（§3.2） | 🟡 待用户确认 |
| 5 | 历史数据清洗后，大量链接会变成「暂无链接，建议上网搜索」，需重采才能拿到真实链接 | 🟡 已知 |
| 6 | `static/logo.png` 需一次性手工生成（裁剪 + 缩放），不引入 Pillow 运行时依赖 | 🟢 一次性 |
| 7 | Spec1 §13 第 1 项「吊销并重新生成 DeepSeek API key」若仍未完成，本次一并处理 | 🔴 必须 |

---

## 12. 明确不做

Spec1 §12 继续有效。本次额外明确：

- 不做深色模式（用户指定白金，非黑金）
- 不做响应式 / 移动端适配
- 不引入 CSS 框架、图标库、Web 字体（保持零外部依赖）
- 不把 Pillow 等图片处理库加入运行时依赖
- **不自动重采历史日期** —— 清洗只做格式规整，重采由管理员手动触发
- 不为 `ref_link` 加可达性探测（HEAD 请求验证 200）—— 属 v2
