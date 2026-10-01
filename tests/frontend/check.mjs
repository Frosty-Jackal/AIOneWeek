/**
 * Spec2 前端行为验证（§3 / §4 / §7 / §8 / §9.3 第 3 层）。
 *
 * 加载**真实的** static/index.html、static/admin.html 与 static/app.js，
 * 用 jsdom 驱动点击，断言 DOM 结果 —— 不是 grep 文案，是真跑。
 *
 * 运行：
 *     node tests/frontend/check.mjs
 *
 * jsdom 是**验证期**依赖，不是运行时依赖（Spec2 §12 要求运行时零外部依赖），
 * 所以它不装进仓库。任选一种方式提供：
 *     npm install --prefix ./.devtools jsdom
 *     JSDOM_PATH=./.devtools/node_modules/jsdom node tests/frontend/check.mjs
 * 或直接 npm i -g jsdom。找不到 jsdom 时本脚本以退出码 2 明确报「跳过」，
 * 不会静默通过。
 */

import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const readStatic = (name) => fs.readFileSync(path.join(ROOT, "static", name), "utf8");

// ---------------------------------------------------------------- jsdom 载入

async function loadJsdom() {
  const candidates = [
    "jsdom",
    process.env.JSDOM_PATH,
    path.join(ROOT, ".devtools/node_modules/jsdom/lib/api.js"),
    path.join(ROOT, ".superpowers/sdd/Spec2/node/node_modules/jsdom/lib/api.js"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      const spec = candidate.startsWith("/") || /^[A-Za-z]:/.test(candidate)
        ? pathToFileURL(candidate).href
        : candidate;
      const mod = await import(spec);
      if (mod.JSDOM) return mod.JSDOM;
    } catch {
      /* 试下一个 */
    }
  }
  return null;
}

// ------------------------------------------------------------------ 断言工具

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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 轮询等待条件成立，避免依赖固定的 sleep 时长。 */
async function until(fn, { timeout = 2000, label = "条件" } = {}) {
  const deadline = Date.now() + timeout;
  for (;;) {
    if (fn()) return true;
    if (Date.now() > deadline) throw new Error(`等待超时：${label}`);
    await sleep(10);
  }
}

// ------------------------------------------------------------------ 页面装配

/**
 * 起一个页面：真实 html + 真实 app.js，fetch 由调用方给定路由表。
 * 返回 { window, document, $, calls, click }。
 */
/**
 * 等 jsdom 自己那次 `DOMContentLoaded` 走完，再让调用方 eval app.js。
 *
 * 不等的话，下面手动 dispatch 的那次会和 jsdom 自然触发的这次各跑一遍 `boot()` ——
 * 监听器被绑两次，一次点击发两个请求。计数类断言（「正好 1 次」）于是只在时序
 * 刚好时才成立：那种绿是运气，不是证明。等到之后再 eval，监听器晚于自然事件注册，
 * 只有手动那一次能触发它，与真实浏览器（`<script>` 在事件之前跑完）一致。
 */
function waitForNaturalDomReady(window) {
  const doc = window.document;
  if (doc.readyState !== "loading") return Promise.resolve();
  return new Promise((resolve) => {
    doc.addEventListener("DOMContentLoaded", resolve, { once: true });
  });
}

async function openPage(JSDOM, htmlFile, routes) {
  const dom = new JSDOM(readStatic(htmlFile), {
    url: "http://localhost:8000/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const calls = [];

  await waitForNaturalDomReady(window);

  // jsdom 未实现的浏览器 API：补成可断言的桩
  window.alert = (m) => calls.push({ path: "alert", body: m });
  window.confirm = () => true;
  const dialogProto = window.HTMLDialogElement && window.HTMLDialogElement.prototype;
  if (dialogProto) {
    dialogProto.showModal = function showModal() {
      if (!this.hasAttribute("open")) this.setAttribute("open", "");
    };
    dialogProto.close = function close() {
      this.removeAttribute("open");
    };
  }

  window.fetch = async (url, opts = {}) => {
    const key = String(url);
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    calls.push({ path: key, method: opts.method || "GET", body });
    const route = routes[key];
    if (!route) throw new Error(`测试未声明路由：${key}`);
    const result = typeof route === "function" ? route({ body, method: opts.method }) : route;
    const resolved = await result;
    const status = resolved.status ?? 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => resolved.body,
    };
  };

  window.eval(readStatic("app.js"));
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));
  await sleep(0);

  return {
    window,
    document: window.document,
    calls,
    $: (sel) => window.document.querySelector(sel),
    click: (sel) => window.document.querySelector(sel).click(),
    weeklyCalls: () => calls.filter((c) => c.path === "/api/weekly").length,
  };
}

const USER = { id: 1, email: "u@example.com", role: "user" };
const ADMIN = { id: 2, email: "a@example.com", role: "admin" };

const WEEK_OK = {
  body: {
    range: { from: "2026-09-23", to: "2026-09-29" },
    days: [{ date: "2026-09-29", status: "success", items: [] }],
    collected_now: [],
  },
};

// ---------------------------------------------------------------------- 用例

async function testLoggedOutNeverShowsFakeProgress(JSDOM) {
  console.log("\n§8 未登录不得进入等待态（Bug 修复）");
  // 后端对无会话的 /api/weekly 一律 401 —— 桩必须照实，否则测不出这个 Bug
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    "/api/weekly": { status: 401, body: { detail: "未登录" } },
  });
  eq("boot 后未登录：#whoami 为空", page.$("#whoami").textContent, "");

  page.click("#btn-weekly");
  await sleep(0);

  eq("点击后 #hero-status 全程为空", page.$("#hero-status").textContent, "");
  ok("登录框立即弹出", page.$("#auth-dialog").hasAttribute("open"));
  eq("未发出 /api/weekly 请求", page.weeklyCalls(), 0);
  ok(
    "页面任何位置都不出现「正在获取当周数据」",
    !page.document.body.textContent.includes("正在获取当周数据"),
  );
}

async function testResumeAfterLogin(JSDOM) {
  console.log("\n§8 登录成功后自动续跑");
  let loggedIn = false;
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": () => (loggedIn ? { body: USER } : { status: 401, body: { detail: "未登录" } }),
    "/api/auth/login": () => {
      loggedIn = true;
      return { body: { ok: true } };
    },
    "/api/weekly": WEEK_OK,
  });

  page.click("#btn-weekly");
  await sleep(0);
  eq("先弹登录框", page.$("#auth-dialog").hasAttribute("open"), true);

  page.$("#login-email").value = "u@example.com";
  page.$("#login-password").value = "1234";
  page.click("#btn-login");
  await until(() => page.weeklyCalls() > 0, { label: "登录后自动续跑的 /api/weekly" });

  eq("登录框自动关闭", page.$("#auth-dialog").hasAttribute("open"), false);
  eq("结果区已展示", page.$("#results").hidden, false);
  ok(
    "状态行为「已采集 …」",
    page.$("#hero-status").textContent.startsWith("已采集 2026-09-23 ~ 2026-09-29"),
    page.$("#hero-status").textContent,
  );
  eq("无需再点一次按钮", page.weeklyCalls(), 1);
}

async function testExpiredSessionStopsTicker(JSDOM) {
  console.log("\n§8 会话中途失效：不残留等待文案");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { body: USER },
    "/api/weekly": { status: 401, body: { detail: "登录已过期" } },
  });
  await sleep(0);

  page.click("#btn-weekly");
  await until(() => page.$("#auth-dialog").hasAttribute("open"), { label: "401 后弹登录框" });
  await sleep(50);

  ok(
    "不残留「正在获取当周数据」",
    !page.$("#hero-status").textContent.includes("正在获取当周数据"),
    page.$("#hero-status").textContent,
  );
}

async function testWaitTickerText(JSDOM) {
  console.log("\n§7 等待文案");
  let release;
  const pending = new Promise((r) => {
    release = r;
  });
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { body: USER },
    "/api/weekly": () => pending.then(() => WEEK_OK),
  });
  await sleep(0);

  page.click("#btn-weekly");
  await sleep(20);
  eq(
    "起始文案",
    page.$("#hero-status").textContent,
    "正在获取当周数据…已等待 0 秒，请耐心等待！",
  );
  ok("不含旧文案「首次需逐日补采」", !page.$("#hero-status").textContent.includes("首次需逐日补采"));
  ok("不含旧文案「约每天 20 秒」", !page.$("#hero-status").textContent.includes("约每天 20 秒"));

  await sleep(1100);
  eq(
    "逐秒递增",
    page.$("#hero-status").textContent,
    "正在获取当周数据…已等待 1 秒，请耐心等待！",
  );

  release();
  await until(() => page.$("#hero-status").textContent.startsWith("已采集"), { label: "采集返回" });
}

async function testCollectedNowVisibility(JSDOM) {
  console.log("\n§3 「本次补采 N 天」只在管理端显示");
  const withGap = {
    body: {
      range: { from: "2026-09-23", to: "2026-09-29" },
      days: [{ date: "2026-09-29", status: "success", items: [] }],
      collected_now: ["2026-09-23"],
    },
  };

  const user = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { body: USER },
    "/api/weekly": withGap,
  });
  await sleep(0);
  user.click("#btn-weekly");
  await until(() => user.$("#hero-status").textContent.startsWith("已采集"), { label: "用户端状态行" });
  eq(
    "用户端状态行严格为「已采集 <起> ~ <止>」",
    user.$("#hero-status").textContent,
    "已采集 2026-09-23 ~ 2026-09-29",
  );

  const admin = await openPage(JSDOM, "admin.html", {
    "/api/auth/me": { body: ADMIN },
    "/api/weekly": withGap,
    "/api/admin/users": { body: [] },
    "/api/admin/sites": { body: [] },
    "/api/admin/eval-set": { body: [] },
  });
  await sleep(0);
  admin.click("#btn-weekly");
  await until(() => admin.$("#hero-status").textContent.startsWith("已采集"), { label: "管理端状态行" });
  eq(
    "管理端仍保留补采天数",
    admin.$("#hero-status").textContent,
    "已采集 2026-09-23 ~ 2026-09-29，本次补采 1 天",
  );
}

const DISCLAIMER = "所有条目均为 AI 生成，请核验参考链接。";

// 拼出来，否则本文件自己就会命中下面那条全仓库零命中扫描
const DEAD_CLASS = "day-" + "foot";

// 7 天各一条，用来暴露「一天一份脚注」的重复
const WEEK_FULL = {
  body: {
    range: { from: "2026-09-23", to: "2026-09-29" },
    days: [
      "2026-09-29",
      "2026-09-28",
      "2026-09-27",
      "2026-09-26",
      "2026-09-25",
      "2026-09-24",
      "2026-09-23",
    ].map((date) => ({
      date,
      status: "success",
      items: [
        {
          tech_name: `T-${date}`,
          tech_content: "内容",
          innovation: "创新",
          scenarios: ["a", "b", "c"],
          publish_date: date,
          ref_link: `https://example.com/${date}`,
        },
      ],
    })),
    collected_now: [],
  },
};

async function testSingleDisclaimer(JSDOM) {
  console.log("\n§4 免责声明全页只有一份");
  const views = [
    ["index.html", USER, {}],
    [
      "admin.html",
      ADMIN,
      {
        "/api/admin/users": { body: [] },
        "/api/admin/sites": { body: [] },
        "/api/admin/eval-set": { body: [] },
      },
    ],
  ];

  for (const [file, me, extra] of views) {
    const page = await openPage(JSDOM, file, {
      "/api/auth/me": { body: me },
      "/api/weekly": WEEK_FULL,
      ...extra,
    });
    await sleep(0);
    page.click("#btn-weekly");
    await until(() => page.$("#hero-status").textContent.startsWith("已采集"), {
      label: `${file} 状态行`,
    });

    eq(`${file}: 7 天卡片已渲染`, page.document.querySelectorAll(".day").length, 7);
    eq(
      `${file}: 无逐日脚注`,
      page.document.querySelectorAll(`.${DEAD_CLASS}`).length,
      0,
      "一天一份脚注，7 天就重复 7 次",
    );
    eq(`${file}: 页面底部声明只有一份`, page.document.querySelectorAll(".foot").length, 1);
    eq(`${file}: 声明措辞不变`, page.$(".foot").textContent.trim(), DISCLAIMER);
  }

  // §4.4：零命中要覆盖 style.css 与 test_theme.mjs，不只是 app.js
  const hits = ["static", "tests/frontend"].flatMap((dir) =>
    fs
      .readdirSync(path.join(ROOT, dir))
      .filter((f) => /\.(css|js|mjs|html)$/.test(f))
      .filter((f) => fs.readFileSync(path.join(ROOT, dir, f), "utf8").includes(DEAD_CLASS))
      .map((f) => `${dir}/${f}`),
  );
  eq("逐日脚注的类名全仓库零命中", hits.join(","), "");
}

// §6.4：用户原文逐字保留，只做半角引号 → 中文双引号、拉丁字符两侧留空格两处排版归一
const HELP_TITLE = "AIOneWeek——让你知道一周内的 AI 前沿技术";
const HELP_PARAS = [
  "您点击中间“查看当周内 AI 前沿技术”后，后台会帮您实时查询当周内 AI 前沿技术，并展示在主界面供您阅读！",
  "每一条前沿 AI 技术条目含有技术内容和创新点，这方便您在阅读 AI 新闻的时候能够快速掌握技术创新点，方便您快速掌握技术要点，以便您深入学习！",
  "此外，每一条目还附带应用场景，能够让您了解这些前沿 AI 技术会如何赋能工作与生活，启发您将人类智慧结晶带出实验室，走向应用！",
];

async function testHelpDialog(JSDOM) {
  console.log("\n§6 顶栏「新手帮助」按钮与帮助弹窗");
  for (const [file, me] of [
    ["index.html", { status: 401, body: { detail: "未登录" } }],
    ["admin.html", { body: ADMIN }],
  ]) {
    const page = await openPage(JSDOM, file, { "/api/auth/me": me });
    await sleep(0);

    const btn = page.$(".who .help-btn");
    ok(`${file}: .who 内有「新手帮助」按钮`, btn !== null);
    if (!btn) continue;
    eq(`${file}: 按钮文案`, btn.textContent.trim(), "新手帮助");
    ok(
      `${file}: 按钮在邮箱展示之前`,
      btn.nextElementSibling?.id === "whoami",
      `next=${btn.nextElementSibling?.id || btn.nextElementSibling?.className}`,
    );

    eq(`${file}: 初始不打开`, page.$("#help-dialog").hasAttribute("open"), false);
    btn.click();
    eq(`${file}: 点击后打开`, page.$("#help-dialog").hasAttribute("open"), true);

    const dlg = page.$("#help-dialog");
    ok(`${file}: 复用 .dialog 金白样式`, dlg.classList.contains("dialog"), dlg.className);
    ok(`${file}: 加 help-dialog 修饰类放宽宽度`, dlg.classList.contains("help-dialog"));
    eq(`${file}: 居中 logo`, page.$("#help-dialog .help-logo").getAttribute("src"), "/static/logo.png");
    eq(`${file}: 标题逐字一致`, page.$("#help-dialog h2").textContent, HELP_TITLE);
    // eq 用 ===，比数组永远为假 —— 拼成字符串再比
    eq(
      `${file}: 三段说明逐字一致`,
      [...page.document.querySelectorAll("#help-dialog .help-body p")]
        .map((p) => p.textContent)
        .join("\n"),
      HELP_PARAS.join("\n"),
    );
    // Esc 与右上角 × 都是 <dialog> 原生行为：× 在 <form method="dialog"> 里，Esc 由浏览器派发。
    // jsdom 两者都不实现，断言它们等于断言 jsdom —— 只能断言结构在，行为留给真机。
    ok(
      `${file}: × 在 method=dialog 的表单里`,
      page.$("#help-dialog .dialog-close-form")?.getAttribute("method") === "dialog",
    );
  }

  // §6.1「未登录时它就是最右」：只在用户端未登录这一种情形下成立 —— 其后除空的 #whoami
  // 就是两个 hidden 项。管理端登录后其后还有「用户端 / 退出」，那时它在右组左端而非最右。
  const anon = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
  });
  await sleep(0);
  const kids = [...anon.document.querySelectorAll(".who > *")];
  const btnIdx = kids.indexOf(anon.$(".who .help-btn"));
  ok(
    "index.html: 未登录时其后无可见内容",
    kids.slice(btnIdx + 1).every((n) => n.hidden || n.textContent.trim() === ""),
    kids.slice(btnIdx + 1).map((n) => `${n.id || n.tagName}${n.hidden ? "(hidden)" : ""}`).join(","),
  );

  // §6.6：不引入任何新依赖
  const SKIP = ["cdn", "unpkg", "fonts.googleapis"];
  const hits = fs
    .readdirSync(path.join(ROOT, "static"))
    .filter((f) => {
      try {
        const text = readStatic(f);
        return SKIP.some((needle) => text.includes(needle));
      } catch {
        return false;
      }
    });
  eq("static/ 下无外部 CDN 引用", hits.join(","), "");
}

async function testStatusVerbCopy(JSDOM) {
  console.log("\n§5 状态行动词");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { body: USER },
    "/api/weekly": WEEK_OK,
  });
  await sleep(0);
  page.click("#btn-weekly");
  await until(() => page.$("#hero-status").textContent.startsWith("已采集"), {
    label: "状态行动词",
  });

  eq("状态行严格等于「已采集 <起> ~ <止>」", page.$("#hero-status").textContent,
    "已采集 2026-09-23 ~ 2026-09-29");
  // statusLabel() 里 success 的药丸本来就是「已采集」，两处从此同词
  eq("药丸与状态行同用「已采集」", page.$(".pill").textContent, "已采集");

  const hits = fs
    .readdirSync(path.join(ROOT, "static"))
    .filter((f) => {
      try {
        return readStatic(f).includes("已展示");
      } catch {
        return false;
      }
    });
  eq("static/ 下「已展示」零命中", hits.join(","), "");
}

/**
 * §9 —— 发码时暂存邮箱，改过邮箱再点注册就先在本地拦下。
 *
 * 这里断两件事：提示文案对，**且没有发出注册请求**。只断文案的话，
 * 「压根没发请求」与「发了但失败了」分不开 —— 所以 `/api/auth/register`
 * 也声明一条 201 路由，让「发出去了」在 calls 里看得见。
 */
async function testRegisterStagedEmailBlocksChangedEmail(JSDOM) {
  console.log("\n§9 改邮箱后点注册：本地拦下，零注册请求");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    "/api/auth/send-code": { status: 204, body: null },
    "/api/auth/register": { status: 201, body: { email: "b@example.com", role: "user" } },
  });

  page.click('[data-goto="view-register"]');
  await sleep(0);

  page.$("#reg-email").value = "a@example.com";
  page.click("#btn-send-reg");
  await until(() => page.$("#auth-msg").textContent.includes("验证码已发送"), {
    label: "发码成功提示（sendCode 是 async，不等它断言会跑在暂存之前）",
  });

  // 用户改主意，换成另一个邮箱 —— 暂存里还是 a
  page.$("#reg-email").value = "b@example.com";
  page.$("#reg-code").value = "1234";
  page.$("#reg-password").value = "1234";
  page.click("#btn-register");
  await sleep(0);

  eq("提示语", page.$("#auth-msg").textContent, "邮箱已变更，请重新获取验证码");
  eq(
    "零 /api/auth/register 请求",
    page.calls.filter((c) => c.path === "/api/auth/register").length,
    0,
  );
}

async function testRegisterUnchangedEmailStillGoesThrough(JSDOM) {
  console.log("\n§9 反向：没改邮箱，注册照常发出");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    "/api/auth/send-code": { status: 204, body: null },
    "/api/auth/register": { status: 201, body: { email: "a@example.com", role: "user" } },
  });

  page.click('[data-goto="view-register"]');
  await sleep(0);

  page.$("#reg-email").value = "a@example.com";
  page.click("#btn-send-reg");
  await until(() => page.$("#auth-msg").textContent.includes("验证码已发送"), {
    label: "发码成功提示",
  });

  page.$("#reg-code").value = "1234";
  page.$("#reg-password").value = "1234";
  page.click("#btn-register");
  // 等提示而不是等 calls：calls 是在 fetch 被调用的瞬间推进去的，此刻
  // await apiJson 还没返回，「注册成功」那句还没写进 #auth-msg。
  await until(() => page.$("#auth-msg").textContent === "注册成功，请登录", {
    label: "注册成功提示",
  });

  const calls = page.calls.filter((c) => c.path === "/api/auth/register");
  eq("注册请求次数", calls.length, 1);
  eq("注册请求里的邮箱", calls[0].body.email, "a@example.com");
}

/**
 * §9.3 第 1 条：失败方向必须是「放行」。
 *
 * 刷新过页面的人（码是在别处发的）没有暂存 —— 此时本地无从判断，若判成
 * 「不一致就拦死」，一个完全合法的注册会寸步难行。这就是前端暂存唯一可能
 * 造成的真实伤害，值得一条用例钉住。
 */
async function testRegisterWithoutStagedEmailIsNotBlocked(JSDOM) {
  console.log("\n§9 无暂存（刷新过页面）：不拦，交服务端裁决");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    "/api/auth/register": { status: 201, body: { email: "a@example.com", role: "user" } },
  });

  page.click('[data-goto="view-register"]');
  await sleep(0);

  // 全程没点过「发送验证码」—— 暂存是 null
  page.$("#reg-email").value = "a@example.com";
  page.$("#reg-code").value = "1234";
  page.$("#reg-password").value = "1234";
  page.click("#btn-register");
  // 先等提示落地：calls 是 fetch 被调用的瞬间推进去的，此刻 Promise 还没回。
  // 等到「非空」而不是等到注册请求出现 —— 两条分支都会写 #auth-msg，所以
  // 「被误拦」在这里是一条干净的 ✗，而不是 until 超时抛异常把整个 runner 掀翻。
  await until(() => page.$("#auth-msg").textContent !== "", { label: "注册结果提示" });

  eq("注册成功提示", page.$("#auth-msg").textContent, "注册成功，请登录");
  eq(
    "注册请求已发出",
    page.calls.filter((c) => c.path === "/api/auth/register").length,
    1,
  );
}

/**
 * §9 —— 「只在发送成功之后暂存」这条纪律也得有测试看着。
 *
 * 前三条用例走的都是发码成功的路径，所以把赋值挪到 `await` 之前它们全绿。
 * 这条走失败路径：发码 500 时若照样把 a 暂存了，用户换个邮箱 b 再注册就会被
 * 本地拦下「邮箱已变更，请重新获取验证码」—— 而 b 的码可能刚从别处要来。
 */
async function testFailedSendDoesNotStageTheEmail(JSDOM) {
  console.log("\n§9 发码失败：不暂存，改邮箱照常注册");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    "/api/auth/send-code": { status: 500, body: { detail: "验证码发送失败，请稍后重试" } },
    "/api/auth/register": { status: 201, body: { email: "b@example.com", role: "user" } },
  });

  page.click('[data-goto="view-register"]');
  await sleep(0);

  page.$("#reg-email").value = "a@example.com";
  page.click("#btn-send-reg");
  // 等失败提示落地：证明那次 async 的 sendCode 已经跑完 —— 暂存若写错了，
  // 此刻也已经写进去了。
  await until(() => page.$("#auth-msg").textContent.includes("失败"), {
    label: "发码失败提示",
  });

  // 换邮箱：a 的码压根没发出去，暂存里不该有 a
  page.$("#reg-email").value = "b@example.com";
  page.$("#reg-code").value = "1234";
  page.$("#reg-password").value = "1234";
  page.click("#btn-register");
  // 这里不能等「非空」：上面那条发码失败提示还挂在 #auth-msg 上，非空是立刻就成立的，
  // 断言会读到一个陈旧的值。等两个分支各自的那句话之一落地 —— 两边都不写就等于超时，
  // 那时抛出来的是真问题。
  await until(
    () =>
      ["注册成功，请登录", "邮箱已变更，请重新获取验证码"].includes(
        page.$("#auth-msg").textContent,
      ),
    { label: "注册结果提示" },
  );

  eq("注册成功提示", page.$("#auth-msg").textContent, "注册成功，请登录");
  const calls = page.calls.filter((c) => c.path === "/api/auth/register");
  eq("注册请求次数", calls.length, 1);
  eq("注册请求里的邮箱", calls[0].body.email, "b@example.com");
}

async function testRefLinkRendering(JSDOM) {
  console.log("\n§9.3 第 3 层 参考链接渲染");
  const page = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { body: USER },
    "/api/weekly": {
      body: {
        range: { from: "2026-09-23", to: "2026-09-29" },
        days: [
          {
            date: "2026-09-29",
            status: "success",
            items: [
              item("有链接", "https://arxiv.org/abs/2609.29808v1"),
              item("无链接", null),
              item("伪协议", "javascript:alert(1)"),
            ],
          },
        ],
        collected_now: [],
      },
    },
  });
  await sleep(0);
  page.click("#btn-weekly");
  await until(() => page.document.querySelectorAll(".item").length === 3, { label: "条目渲染" });

  const [withLink, noLink, badScheme] = page.document.querySelectorAll(".item");

  const anchor = withLink.querySelector("a.ref");
  ok("有链接 → 渲染 <a class=ref>", !!anchor);
  eq("href 原样保留", anchor && anchor.getAttribute("href"), "https://arxiv.org/abs/2609.29808v1");
  eq("新标签打开", anchor && anchor.getAttribute("target"), "_blank");
  eq("rel=noopener noreferrer", anchor && anchor.getAttribute("rel"), "noopener noreferrer");

  const fallback = noLink.querySelector(".ref-none");
  ok("无链接 → 渲染 .ref-none", !!fallback);
  eq("兜底文案", fallback && fallback.textContent, "暂无链接，建议上网搜索");
  eq("无链接时不渲染 <a>", noLink.querySelectorAll("a.ref").length, 0);

  ok("javascript: 伪协议被拦下", !badScheme.querySelector("a.ref"));
  eq("伪协议走兜底", badScheme.querySelectorAll(".ref-none").length, 1);
}

function item(name, refLink) {
  return {
    tech_name: name,
    tech_content: "内容",
    innovation: "创新",
    scenarios: ["a", "b", "c"],
    publish_date: "2026年9月29日",
    ref_link: refLink,
  };
}

async function testAdminPasswordButton(JSDOM) {
  console.log("\n§4 「查看」→「查看密码」且不折行");
  const page = await openPage(JSDOM, "admin.html", {
    "/api/auth/me": { body: ADMIN },
    "/api/admin/users": {
      body: [
        {
          id: 1,
          email: "u@example.com",
          role: "user",
          password_masked: "12****",
          call_count: 3,
          avg_score: null,
          rating_count: 0,
          created_at: "2026-09-01 00:00:00",
        },
      ],
    },
    "/api/admin/sites": { body: [] },
    "/api/admin/eval-set": { body: [] },
    "/api/admin/users/1/password": { body: { password: "1234" } },
  });
  await sleep(0);

  page.click('.tab[data-tab="data"]');
  await until(() => page.document.querySelectorAll("#users-table tbody tr").length === 1, {
    label: "用户表渲染",
  });

  const cell = page.document.querySelector("#users-table tbody tr td:last-child");
  const btn = cell.querySelector("button");
  eq("按钮文案", btn.textContent, "查看密码");
  ok("操作列带 ops class（white-space: nowrap）", cell.classList.contains("ops"));

  btn.click();
  await until(() => page.document.querySelector("#users-table tbody tr td:nth-child(4)").textContent === "1234", {
    label: "解密回填密码",
  });
  ok("点击后第 4 列显示明文", true);
}

/** 元素自身及其所有祖先都没有 hidden 才算可见（jsdom 不做布局）。 */
function isVisible(el) {
  for (let node = el; node; node = node.parentElement) {
    if (node.hasAttribute && node.hasAttribute("hidden")) return false;
  }
  return true;
}

async function testSupportEmailOnAllViews(JSDOM) {
  console.log("\n§6 客服邮箱在三个视图下常驻");
  for (const file of ["index.html", "admin.html"]) {
    const routes = { "/api/auth/me": { status: 401, body: { detail: "未登录" } } };
    if (file === "admin.html") {
      routes["/api/admin/users"] = { body: [] };
      routes["/api/admin/sites"] = { body: [] };
      routes["/api/admin/eval-set"] = { body: [] };
    }
    const page = await openPage(JSDOM, file, routes);
    await sleep(0);

    const foot = page.$(".dialog-foot");
    ok(`${file}: 存在 .dialog-foot`, !!foot);
    if (!foot) continue;

    const link = foot.querySelector("a");
    eq(`${file}: mailto 链接`, link && link.getAttribute("href"), "mailto:frostyj@qq.com");
    eq(`${file}: 文案`, foot.textContent, "客服邮箱：frostyj@qq.com");

    // 位置：在 #auth-msg 之下（错误提示不挤压它）
    const msg = page.$("#auth-msg");
    ok(
      `${file}: 位于 #auth-msg 之后`,
      msg.compareDocumentPosition(foot) & 4 /* DOCUMENT_POSITION_FOLLOWING */,
    );
    ok(
      `${file}: 与 #auth-msg 同属弹窗直接子元素（不在任何 .view 内）`,
      foot.parentElement === msg.parentElement && foot.parentElement.id === "auth-dialog",
    );

    const views = [...page.document.querySelectorAll("#auth-dialog .view")];
    ok(`${file}: 弹窗有视图`, views.length > 0);

    // 逐个切过去：邮箱在每一个视图下都必须可见。视图个数按文件实际有的算 ——
    // admin.html 只有「管理员登录」一个视图，把用户端的三视图要求套上去是错的。
    for (const view of views) {
      const id = view.id;
      const goto = page.document.querySelector(`[data-goto="${id}"]`);
      if (goto) {
        goto.click();
        await sleep(0);
      }
      ok(`${file}: 「${id}」视图下邮箱可见`, isVisible(foot));
    }

    if (file === "index.html") {
      eq(
        "index.html: 用户端恰有 3 个视图（登录 / 验证码登录 / 注册）",
        views.map((v) => v.id).join(","),
        "view-login,view-code,view-register",
      );
    }
  }
}

async function testSubtitleCopy(JSDOM) {
  console.log("\n§2 副标题：用户端改写，管理端不动");
  const user = await openPage(JSDOM, "index.html", {
    "/api/auth/me": { status: 401, body: { detail: "未登录" } },
  });
  await sleep(0);
  eq(
    "用户端副标题",
    user.$(".hero .sub").textContent,
    "前 7 天到底有哪些前沿 AI 技术？单击按钮立即查看！",
  );

  const admin = await openPage(JSDOM, "admin.html", {
    "/api/auth/me": { body: ADMIN },
    "/api/admin/users": { body: [] },
    "/api/admin/sites": { body: [] },
    "/api/admin/eval-set": { body: [] },
  });
  await sleep(0);
  eq("管理端副标题不变", admin.$(".hero .sub").textContent, "滚动当周 7 天；缺口会自动串行补采");

  // §2.3：旧文案零命中（覆盖 static/ 下每一个文本资产，不只 index.html）
  const stale = "滚动当周 7 天，AI 前沿技术一处看完";
  const hits = fs
    .readdirSync(path.join(ROOT, "static"))
    .filter((f) => {
      try {
        return readStatic(f).includes(stale);
      } catch {
        return false;
      }
    });
  eq("旧副标题在 static/ 下零命中", hits.join(","), "");
}

async function testBrandLogo(JSDOM) {
  console.log("\n§5.5 顶栏 logo");
  for (const file of ["index.html", "admin.html"]) {
    const page = await openPage(JSDOM, file, {
      "/api/auth/me": { status: 401, body: { detail: "未登录" } },
    });
    await sleep(0);
    const img = page.$(".brand img.logo");
    ok(`${file}: .brand 内有 img.logo`, !!img);
    if (!img) continue;
    eq(`${file}: src`, img.getAttribute("src"), "/static/logo.png");
    eq(`${file}: alt 必需（无障碍）`, img.getAttribute("alt"), "AIOneWeek");
    ok(`${file}: logo 在品牌文字之前`, img.nextElementSibling?.classList.contains("name"));
    ok(`${file}: 保留文字品牌名`, page.$(".brand .name")?.textContent === "AIOneWeek");
  }
}

// ------------------------------------------------------------------ 入口

const JSDOM = await loadJsdom();
if (!JSDOM) {
  console.error("SKIP: 未找到 jsdom，前端行为验证未执行。");
  console.error("      安装：npm install --prefix ./.devtools jsdom");
  console.error("      然后：JSDOM_PATH=./.devtools/node_modules/jsdom node tests/frontend/check.mjs");
  process.exit(2);
}

console.log("Spec2 前端行为验证（真实 html + 真实 app.js + jsdom）");
await testLoggedOutNeverShowsFakeProgress(JSDOM);
await testResumeAfterLogin(JSDOM);
await testExpiredSessionStopsTicker(JSDOM);
await testWaitTickerText(JSDOM);
await testCollectedNowVisibility(JSDOM);
await testSingleDisclaimer(JSDOM);
await testHelpDialog(JSDOM);
await testStatusVerbCopy(JSDOM);
await testRegisterStagedEmailBlocksChangedEmail(JSDOM);
await testRegisterUnchangedEmailStillGoesThrough(JSDOM);
await testRegisterWithoutStagedEmailIsNotBlocked(JSDOM);
await testFailedSendDoesNotStageTheEmail(JSDOM);
await testRefLinkRendering(JSDOM);
await testAdminPasswordButton(JSDOM);
await testSupportEmailOnAllViews(JSDOM);
await testSubtitleCopy(JSDOM);
await testBrandLogo(JSDOM);

console.log(`\n${passed} 项通过，${failures.length} 项失败`);
for (const f of failures) console.log(`  ✗ ${f}`);
process.exit(failures.length ? 1 : 0);
