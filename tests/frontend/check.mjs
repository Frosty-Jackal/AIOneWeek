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
async function openPage(JSDOM, htmlFile, routes) {
  const dom = new JSDOM(readStatic(htmlFile), {
    url: "http://localhost:8000/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const calls = [];

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
    "状态行为「已展示 …」",
    page.$("#hero-status").textContent.startsWith("已展示 2026-09-23 ~ 2026-09-29"),
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
  await until(() => page.$("#hero-status").textContent.startsWith("已展示"), { label: "采集返回" });
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
  await until(() => user.$("#hero-status").textContent.startsWith("已展示"), { label: "用户端状态行" });
  eq(
    "用户端状态行严格为「已展示 <起> ~ <止>」",
    user.$("#hero-status").textContent,
    "已展示 2026-09-23 ~ 2026-09-29",
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
  await until(() => admin.$("#hero-status").textContent.startsWith("已展示"), { label: "管理端状态行" });
  eq(
    "管理端仍保留补采天数",
    admin.$("#hero-status").textContent,
    "已展示 2026-09-23 ~ 2026-09-29，本次补采 1 天",
  );
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
await testRefLinkRendering(JSDOM);
await testAdminPasswordButton(JSDOM);

console.log(`\n${passed} 项通过，${failures.length} 项失败`);
for (const f of failures) console.log(`  ✗ ${f}`);
process.exit(failures.length ? 1 : 0);
