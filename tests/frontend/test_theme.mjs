/**
 * Spec2 §5 / §6 主题与结构的静态审计。
 *
 * 主题的正确性大部分是「有没有按表改」和「有没有踩反例」，这两件事都在文本里
 * 可判定，所以这里不跑浏览器：解析 style.css 成「选择器 → 声明」，再逐条对
 * §5.4 的表格、§5.6 的反例清单、§5.3 的对比度账。
 *
 * 对比度不是抄 §5.3 的数字，而是从 CSS 里真实的令牌值重算 —— 抄数字只能证明
 * 表格抄对了，重算才能发现有人改了令牌却没改账。
 *
 * 运行（不需要 jsdom）：
 *     node tests/frontend/test_theme.mjs
 */

import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const STATIC = path.join(ROOT, "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf8");

let passed = 0;
const failures = [];

function ok(name, condition, detail = "") {
  if (condition) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  } else {
    failures.push(`${name}${detail ? ` —— ${detail}` : ""}`);
    console.log(`  ✗ ${name}${detail ? ` —— ${detail}` : ""}`);
  }
}

function eq(name, actual, expected) {
  ok(name, actual === expected, `实际 ${JSON.stringify(actual)}，期望 ${JSON.stringify(expected)}`);
}

// ------------------------------------------------------------- CSS 解析

const CSS = read("style.css").replace(/\/\*[\s\S]*?\*\//g, "");

/** [{selectors: string[], decls: {prop: value}}]，保持源文件顺序。 */
function parseRules(css) {
  const rules = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const selectors = m[1].split(",").map((s) => s.trim().replace(/\s+/g, " ")).filter(Boolean);
    const decls = {};
    for (const piece of m[2].split(";")) {
      const i = piece.indexOf(":");
      if (i < 0) continue;
      decls[piece.slice(0, i).trim()] = piece.slice(i + 1).trim();
    }
    rules.push({ selectors, decls });
  }
  return rules;
}

const RULES = parseRules(CSS);

/** 某选择器的合并声明（后写的覆盖先写的），带 `!important` 的一并归一化。 */
function declsOf(selector) {
  const merged = {};
  for (const rule of RULES) {
    if (rule.selectors.includes(selector)) Object.assign(merged, rule.decls);
  }
  return merged;
}

const has = (selector) => RULES.some((r) => r.selectors.includes(selector));

/** 全是 `@media` 内的规则才用得上；本文件目前不写断点。 */
function rulesMatching(pred) {
  return RULES.filter((r) => r.selectors.some(pred));
}

// ------------------------------------------------------------- 令牌与对比度

const ROOT_DECLS = declsOf(":root");
const token = (name) => ROOT_DECLS[name];

/** `var(--x)` → 令牌值；已是字面量则原样返回。 */
function resolve(value) {
  const m = /^var\((--[a-z0-9-]+)\)$/.exec(value || "");
  return m ? token(m[1]) : value;
}

function luminance(hex) {
  if (typeof hex !== "string" || !/^#[0-9a-f]{6}$/i.test(hex)) return NaN;
  const ch = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

function contrast(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  // 令牌缺失时返回 NaN，让断言失败而不是让整个脚本崩掉 —— 崩掉会掩盖后面所有断言。
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

// ------------------------------------------------------------- 用例

function testTokens() {
  console.log("\n§5.2 设计令牌全量替换");
  const expected = {
    "--bg": "#FBFAF6",
    "--bg-soft": "#F5F1E8",
    "--panel": "#FFFFFF",
    "--ink": "#23211C",
    "--ink-2": "#6E6659",
    "--ink-3": "#797263",
    "--line": "#EBE5D8",
    "--line-2": "#DFD6C2",
    "--gold": "#8C6B1F",
    "--gold-deep": "#6E5314",
    "--gold-line": "#C9A227",
    "--gold-soft": "#F6EFDD",
    "--gold-ink": "#FFFFFF",
    "--ok": "#1F7A4D",
    "--warn": "#9A6B12",
    "--bad": "#B23A3A",
    "--radius": "10px",
    "--radius-lg": "14px",
  };
  for (const [name, want] of Object.entries(expected)) {
    eq(`:root ${name}`, token(name), want);
  }
  ok('--shadow 已定义', /rgba\(60\s*,\s*48\s*,\s*20/.test(token("--shadow") || ""), token("--shadow"));

  // Spec1 的令牌必须废弃，不能留成半新半旧
  ok("Spec1 的 --brand 已删除", token("--brand") === undefined);
  ok("Spec1 的 --brand-ink 已删除", token("--brand-ink") === undefined);
}

function testContrast() {
  console.log("\n§5.3 对比度账（从 CSS 实际令牌重算）");
  const pairs = [
    ["--gold", "--panel", 4.5],
    ["--gold-deep", "--panel", 4.5],
    ["--gold-deep", "--gold-soft", 4.5],
    ["--gold-ink", "--gold", 4.5],
    ["--ink", "--bg", 4.5],
    ["--ink", "--panel", 4.5],
    ["--ink-2", "--panel", 4.5],
    ["--ink-2", "--bg-soft", 4.5],
    ["--ink-3", "--panel", 4.5],
    ["--ink-3", "--bg", 4.5],
    ["--ok", "--panel", 4.5],
    ["--warn", "--panel", 4.5],
    ["--bad", "--panel", 4.5],
    ["--gold", "--bg", 4.5],
  ];
  for (const [fg, bg, min] of pairs) {
    const ratio = contrast(token(fg), token(bg));
    ok(
      `${fg} on ${bg} ≥ ${min}:1`,
      ratio >= min,
      `实算 ${ratio.toFixed(2)}:1`,
    );
  }

  // §5.3 的两条坑点：把它们钉成断言，改令牌时会被拦住
  const trap1 = contrast(token("--gold"), token("--gold-soft"));
  ok(
    "坑点一：--gold 落在 --gold-soft 上确实不达标（故 12px 小字必须用 --gold-deep）",
    trap1 < 4.5,
    `实算 ${trap1.toFixed(2)}:1，若已达标则 §5.4 的禁令可以放宽，需同步改文档`,
  );
  const trap2 = contrast(token("--ink-3"), token("--bg-soft"));
  ok(
    "坑点二：--ink-3 落在 --bg-soft 上不达标（故 --ink-3 只能用在白底/暖白底）",
    trap2 < 4.5,
    `实算 ${trap2.toFixed(2)}:1`,
  );
}

function testForbidden() {
  console.log("\n§5.6 反例清单");
  const files = fs.readdirSync(STATIC).filter((f) => /\.(css|html|js|svg)$/.test(f));

  // §5.7 验收：Spec1 的三个冷色零命中
  for (const stale of ["#2f6df6", "#eef3ff", "#f5f6f8"]) {
    const hits = files.filter((f) => read(f).toLowerCase().includes(stale));
    eq(`static/ 下无 ${stale}`, hits.join(","), "");
  }

  // 亮金不得承载文字：全表里只允许 --gold-line 用作装饰
  const brightGold = ["#d4af37", "#f5b301", "#ffd700"];
  const textColorRules = rulesMatching((s) => !/:(hover|focus|active)\b/.test(s)).filter(
    (r) => r.decls.color || r.decls["border-color"],
  );
  for (const hex of brightGold) {
    const bad = textColorRules.filter((r) =>
      [r.decls.color, r.decls["background"]].some((v) => (v || "").toLowerCase() === hex),
    );
    eq(`无规则用 ${hex} 承载文字/底色`, bad.map((r) => r.selectors.join(",")).join("|"), "");
  }
  ok(
    "无规则把亮金写进 color（只允许 --gold-line 做装饰）",
    !/color\s*:\s*#(d4af37|f5b301|ffd700)/i.test(CSS),
  );

  // 主按钮 hover 只许变深（变浅会让白字跌穿 4.5:1）
  const primaryHover = declsOf("button.primary:hover");
  ok(
    "主按钮 hover 不用 filter: brightness 提亮",
    !/brightness/.test(primaryHover.filter || ""),
    primaryHover.filter,
  );
  eq("主按钮 hover 背景用 --gold-deep", primaryHover.background, "var(--gold-deep)");

  // 禁止大面积深色 / 渐变铺底 / 发光
  for (const sel of ["body", ".topbar", "main", ".hero"]) {
    const d = declsOf(sel);
    ok(`${sel} 无渐变铺底`, !/gradient/.test(d.background || d["background-image"] || ""));
  }
  ok("全表无 text-shadow 发光", !/text-shadow/.test(CSS));
  // 金色只允许做无模糊的实线（顶栏那条 inset 细线），有模糊半径就是光晕
  const goldGlow = RULES.filter((r) => /box-shadow/.test(Object.keys(r.decls).join()))
    .map((r) => ({ sel: r.selectors.join(","), shadow: r.decls["box-shadow"] || "" }))
    .filter(({ shadow }) => shadow.includes("var(--gold-line)"))
    .filter(({ shadow }) => {
      // 剥掉颜色后按位置取：inset? <x> <y> <blur> <spread>。写成 0 时没有单位，
      // 用 px 去正则匹配会漏判，所以按 token 位置取。
      const parts = shadow.replace(/var\([^)]*\)/g, "").trim().split(/\s+/).filter((t) => t !== "inset");
      const blur = parts[2] === undefined ? 0 : parseFloat(parts[2]);
      return !(blur === 0);
    });
  eq(
    "金色 box-shadow 只做无模糊实线（无光晕）",
    goldGlow.map((g) => `${g.sel} { ${g.shadow} }`).join(" | "),
    "",
  );

  // 顶栏只许一条金色横贯带
  const topbar = declsOf(".topbar");
  const bands = (topbar["box-shadow"] || "").match(/inset/g) || [];
  eq("顶栏只有一条金色横贯带", bands.length, 1);
  ok("顶栏的带子是 --gold-line 且 2px", /inset 0 -2px 0 var\(--gold-line\)/.test(topbar["box-shadow"] || ""));

  // 焦点环：每个输入类选择器都要有可见 focus
  const inputs = ["input", ".dialog input", ".collect-bar input[type=\"date\"]", ".panel-head input[type=\"text\"]"];
  for (const sel of inputs) {
    const focus = declsOf(`${sel}:focus`);
    ok(
      `${sel}:focus 有可见焦点环`,
      /var\(--gold\)/.test(focus["border-color"] || "") &&
        /3px\s+var\(--gold-soft\)/.test(focus["box-shadow"] || ""),
      JSON.stringify(focus),
    );
    eq(`${sel}:focus 移除默认 outline`, focus.outline, "none");
  }

  // 金色浅底上的小字必须用 --gold-deep
  const conflicts = rulesMatching((s) => true).filter(
    (r) =>
      /var\(--gold-soft\)/.test(r.decls.background || "") && /var\(--gold\)\s*$/.test(r.decls.color || ""),
  );
  eq(
    "无「金浅底 + --gold 文字」的越界组合",
    conflicts.map((r) => r.selectors.join(",")).join("|"),
    "",
  );
}

function testComponents() {
  console.log("\n§5.4 逐组件改法");

  const check = (selector, expectations) => {
    const d = declsOf(selector);
    for (const [prop, want] of Object.entries(expectations)) {
      eq(`${selector} { ${prop} }`, d[prop], want);
    }
  };

  ok(".topbar 存在", has(".topbar"));
  check(".topbar", {
    background: "var(--panel)",
    "border-bottom": "1px solid var(--line)",
  });

  check(".brand", { display: "flex", "align-items": "center", gap: "10px" });
  check(".brand img.logo", { height: "32px", width: "auto", display: "block" });
  check(".brand .name", { "font-weight": "700", color: "var(--gold)", "letter-spacing": ".5px" });
  ok(".brand .tag 存在", has(".brand .tag"));
  check(".brand .tag", {
    background: "var(--gold-soft)",
    color: "var(--gold-deep)",
    "border-radius": "999px",
  });
  ok(
    ".brand .tag 边框用 --gold-line",
    /1px solid var\(--gold-line\)/.test(declsOf(".brand .tag").border || ""),
  );

  check(".link", { color: "var(--gold)" });
  check("button.primary", {
    background: "var(--gold)",
    color: "var(--gold-ink)",
    "border": "1px solid var(--gold)",
  });
  ok(".link:hover 仍有下划线", declsOf(".link:hover")["text-decoration"] === "underline");

  check("button.ghost", { background: "var(--panel)" });
  ok(
    "button.ghost 边框用 --line-2",
    /1px solid var\(--line-2\)/.test(declsOf("button.ghost").border || ""),
  );
  check("button.ghost:hover", { "border-color": "var(--gold)", color: "var(--gold)" });

  check(".tab", { color: "var(--ink-2)" });
  check(".tab.active", {
    background: "var(--panel)",
    color: "var(--gold)",
    "font-weight": "600",
    "border-color": "var(--line)",
    "border-top": "2px solid var(--gold-line)",
  });

  for (const card of [".day", ".panel", ".rating"]) {
    check(card, {
      background: "var(--panel)",
      border: "1px solid var(--line)",
      "box-shadow": "var(--shadow)",
    });
  }
  for (const big of [".day", ".panel"]) {
    check(big, { "border-radius": "var(--radius-lg)" });
  }

  check(".day-head h3", {
    color: "var(--ink)",
    "border-left": "3px solid var(--gold-line)",
    "padding-left": "10px",
  });

  check(".pill", {
    background: "var(--gold-soft)",
    color: "var(--gold-deep)",
    "border": "1px solid var(--gold-line)",
  });
  check(".pill.ok", { color: "var(--ok)", background: "var(--bg-soft)", border: "1px solid var(--line-2)" });
  check(".pill.warn", { color: "var(--warn)", background: "var(--bg-soft)", border: "1px solid var(--line-2)" });
  check(".pill.muted", { color: "var(--ink-2)", background: "var(--bg-soft)", border: "1px solid var(--line-2)" });

  // §5.4 点名要替换掉 Spec1 的蓝色 #eef3ff
  check(".field .label", {
    background: "var(--gold-soft)",
    color: "var(--gold-deep)",
    border: "1px solid var(--gold-line)",
  });

  check(".item", { "border-top": "1px dashed var(--line-2)" });
  check(".meta a.ref", { color: "var(--gold)" });
  check(".meta .ref-none", { color: "var(--ink-3)" });

  check(".star", { color: "#DCD5C6" });
  check(".star:hover", { color: "var(--gold-line)" });
  check(".star.on", { color: "var(--gold-line)" });

  check("table.grid th", { background: "var(--bg-soft)", color: "var(--ink-2)" });
  ok(
    "table.grid 行分隔用 --line",
    /1px solid var\(--line\)/.test(declsOf("table.grid td")["border-bottom"] || ""),
    declsOf("table.grid td")["border-bottom"],
  );
  check("table.grid tbody tr:hover", { background: "var(--bg)" });

  check(".dialog", {
    background: "var(--panel)",
    "border-top": "3px solid var(--gold-line)",
    "box-shadow": "0 18px 48px rgba(60,48,20,.18)",
  });
  ok(
    ".dialog 边框用 --line-2",
    /1px solid var\(--line-2\)/.test(declsOf(".dialog").border || ""),
  );
  eq(".dialog::backdrop 遮罩", declsOf(".dialog::backdrop").background, "rgba(40,33,16,.32)");

  check(".dialog .or", { color: "var(--ink-3)" });
  check(".foot", {
    color: "var(--ink-3)",
    "border-top": "1px solid var(--line)",
    "margin-top": "40px",
    "padding-top": "16px",
  });

  // 旧的冷灰脚注必须换掉（#97a0ad 在白底只有 ≈2.6:1）
  ok("无残留冷灰 #97a0ad", !/#97a0ad/i.test(CSS));
  check(".day-foot", { color: "var(--ink-3)" });

  // §6 的客服邮箱样式
  check(".dialog-foot", {
    "margin": "10px 0 0",
    "padding-top": "10px",
    "border-top": "1px solid var(--line)",
    "font-size": "12px",
    "color": "var(--ink-2)",
    "text-align": "center",
  });
  check(".dialog-foot a", { color: "var(--gold)" });

  // §5.7 150% 缩放不得出现横向滚动条：窄视口下弹窗与表格必须能收
  ok(
    ".dialog 宽度在窄视口下会收（min/calc/max-width 之一）",
    /min\(|calc\(|max-width/.test(declsOf(".dialog").width || "") ||
      /max-width/.test(declsOf(".dialog")["max-width"] || ""),
    declsOf(".dialog").width,
  );
  ok(
    "含宽表格的 .panel 可横向自滚",
    declsOf(".panel")["overflow-x"] === "auto",
    declsOf(".panel")["overflow-x"],
  );
}

function testMarkup() {
  console.log("\n§5.5 / §6 两个 html 的结构");
  for (const file of ["index.html", "admin.html"]) {
    const html = read(file);
    const brand = /<div class="brand">([\s\S]*?)<\/div>/.exec(html);
    ok(`${file}: 有 .brand`, !!brand);
    const inner = brand ? brand[1] : "";
    ok(
      `${file}: .brand 内有 <img class="logo" src="/static/logo.png" alt="AIOneWeek">`,
      /<img class="logo" src="\/static\/logo\.png" alt="AIOneWeek">/.test(inner),
      inner.trim(),
    );
    ok(`${file}: logo 在文字之前`, inner.indexOf("<img") < inner.indexOf('class="name"'));
    ok(`${file}: .brand 保留文字品牌名`, /<span class="name">AIOneWeek<\/span>/.test(inner), inner.trim());

    // 客服邮箱：必须在 #auth-msg 之后、且不在任何 .view 里（三个视图常驻）
    const foot = html.indexOf('class="dialog-foot"');
    ok(`${file}: 有 .dialog-foot`, foot > 0);
    ok(`${file}: .dialog-foot 在 #auth-msg 之后`, foot > html.indexOf('id="auth-msg"'));
    ok(
      `${file}: .dialog-foot 文案与 mailto`,
      /<p class="dialog-foot">客服邮箱：<a href="mailto:frostyj@qq\.com">frostyj@qq\.com<\/a><\/p>/.test(html),
    );
    const dialog = html.slice(html.indexOf('<dialog id="auth-dialog"'));
    void dialog;
  }

  const adminBrand = /<div class="brand">([\s\S]*?)<\/div>/.exec(read("admin.html"))[1];
  ok(
    "admin.html: 管理端标签在 .name 之后",
    adminBrand.indexOf('class="name"') < adminBrand.indexOf('class="tag"'),
    adminBrand.trim(),
  );
  ok("admin.html: 保留 .tag 管理端", /<span class="tag">管理端<\/span>/.test(adminBrand));
}

function testViewStructure() {
  console.log("\n§6.2 客服邮箱在三个视图下常驻（DOM 结构）");
  for (const file of ["index.html", "admin.html"]) {
    const html = read(file);
    const dialog = html.slice(html.indexOf('<dialog id="auth-dialog"'));
    const views = [...dialog.matchAll(/<div class="view"[^>]*>/g)].map((m) => m.index);
    const foot = dialog.indexOf('class="dialog-foot"');
    // 判据：foot 之前出现的 view 开标签都已闭合 —— 用「最后一个 view 的 </div> 在 foot 之前」
    // 近似。更硬的做法是跑 DOM，这里只做结构兜底；真行为由 check.mjs 断言。
    ok(`${file}: .dialog-foot 在最后一个 .view 开标签之后`, foot > Math.max(...views), `foot=${foot}, views=${views}`);
    ok(`${file}: #auth-msg 与 .dialog-foot 相邻`, /id="auth-msg"><\/p>\s*<p class="dialog-foot">/.test(dialog));
  }
}

// ------------------------------------------------------------------ 入口

console.log("Spec2 主题与结构审计（static/style.css + 两个 html）");
testTokens();
testContrast();
testForbidden();
testComponents();
testMarkup();
testViewStructure();

console.log(`\n${passed} 项通过，${failures.length} 项失败`);
for (const f of failures) console.log(`  ✗ ${f}`);
process.exit(failures.length ? 1 : 0);
