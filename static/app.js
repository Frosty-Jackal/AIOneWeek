/* AIOneWeek 前端（Spec1 §7）。无框架、无打包，浏览器直跑。 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const PAGE = document.body.dataset.page; // "index" | "admin"

  const DAY_STATUS = {
    empty: "这日无前沿 AI 技术",
    failed: "该日采集失败，稍后自动重试",
    parse_failed: "该日数据解析异常，管理员可修正",
    missing: "该日数据待补",
  };

  const GRADE = { success: "ok", empty: "muted", failed: "warn", parse_failed: "warn", missing: "muted" };

  /* 已评分的日期：当次会话内不再重复弹出评分条（§7.1） */
  const ratedDates = new Set();
  let pendingAfterLogin = null;

  // ---------- 基础请求 ----------

  async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return res;
  }

  async function apiJson(path, opts) {
    const res = await api(path, opts);
    let data = null;
    try {
      data = res.status === 204 ? null : await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const err = new Error(detailOf(data) || `请求失败（${res.status}）`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function detailOf(data) {
    if (!data) return "";
    const d = data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) return d[0].msg || "";
    return "";
  }

  function setStatus(text, kind = "") {
    const el = $("#hero-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "hint" + (kind ? " " + kind : "");
  }

  // ---------- 登录态 ----------

  let currentUser = null;

  async function loadMe() {
    try {
      currentUser = await apiJson("/api/auth/me");
    } catch (_) {
      currentUser = null;
    }
    renderWho();
    return currentUser;
  }

  function renderWho() {
    const who = $("#whoami");
    if (who) who.textContent = currentUser ? currentUser.email : "";
    const logout = $("#btn-logout");
    if (logout) logout.hidden = !currentUser;
    const adminLink = $("#link-admin");
    if (adminLink) adminLink.hidden = !currentUser || currentUser.role !== "admin";
  }

  /** 需要登录才能跑的动作：401 时弹登录框，登录成功后自动续跑。 */
  async function withAuth(fn) {
    try {
      return await fn();
    } catch (err) {
      if (err.status === 401) {
        pendingAfterLogin = fn;
        openAuth("view-login");
        return undefined;
      }
      throw err;
    }
  }

  // ---------- 登录弹窗 ----------

  function openAuth(view) {
    const dlg = $("#auth-dialog");
    if (!dlg) return;
    showView(view || "view-login");
    msg("");
    if (!dlg.open) dlg.showModal();
  }

  function showView(id) {
    $$(".view").forEach((v) => (v.hidden = v.id !== id));
  }

  function msg(text, kind = "") {
    const el = $("#auth-msg");
    if (!el) return;
    el.textContent = text || "";
    el.className = "dialog-msg" + (kind ? " " + kind : "");
  }

  function countdown(btn) {
    let left = 120;
    btn.disabled = true;
    const tick = () => {
      if (left <= 0) {
        btn.disabled = false;
        btn.textContent = "发送验证码";
        return;
      }
      btn.textContent = `重新发送(${left}s)`;
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  }

  async function sendCode(btn, emailInput, purpose) {
    const email = emailInput.value.trim();
    if (!email) return msg("请先填写邮箱", "bad");
    btn.disabled = true;
    try {
      await apiJson("/api/auth/send-code", { method: "POST", body: { email, purpose } });
      msg("验证码已发送，请查收邮件", "good");
      countdown(btn);
    } catch (err) {
      btn.disabled = false;
      msg(err.message, "bad");
    }
  }

  async function afterAuthOk() {
    await loadMe();
    const dlg = $("#auth-dialog");
    if (dlg && dlg.open) dlg.close();
    const next = pendingAfterLogin;
    pendingAfterLogin = null;
    if (next) await next();
  }

  function wireAuthDialog() {
    if (!$("#auth-dialog")) return;

    $$("[data-goto]").forEach((b) =>
      b.addEventListener("click", () => {
        msg("");
        showView(b.dataset.goto);
      })
    );

    $("#btn-login")?.addEventListener("click", async () => {
      const email = $("#login-email").value.trim();
      const password = $("#login-password").value;
      if (!email || !password) return msg("请填写邮箱和密码", "bad");
      try {
        await apiJson("/api/auth/login", { method: "POST", body: { email, password } });
        await afterAuthOk();
      } catch (err) {
        msg(err.message, "bad");
      }
    });

    $("#btn-send-login")?.addEventListener("click", (e) =>
      sendCode(e.currentTarget, $("#code-email"), "login")
    );
    $("#btn-send-reg")?.addEventListener("click", (e) =>
      sendCode(e.currentTarget, $("#reg-email"), "register")
    );

    $("#btn-login-code")?.addEventListener("click", async () => {
      const email = $("#code-email").value.trim();
      const code = $("#code-code").value.trim();
      if (!email || !code) return msg("请填写邮箱和验证码", "bad");
      try {
        await apiJson("/api/auth/login-code", { method: "POST", body: { email, code } });
        await afterAuthOk();
      } catch (err) {
        msg(err.message, "bad");
      }
    });

    $("#btn-register")?.addEventListener("click", async () => {
      const email = $("#reg-email").value.trim();
      const code = $("#reg-code").value.trim();
      const password = $("#reg-password").value;
      if (!email || !code || !password) return msg("请填写全部字段", "bad");
      try {
        await apiJson("/api/auth/register", { method: "POST", body: { email, code, password } });
        msg("注册成功，请登录", "good");
        $("#login-email").value = email;
        showView("view-login");
      } catch (err) {
        msg(err.message, "bad");
      }
    });

    $("#btn-logout")?.addEventListener("click", async () => {
      try {
        await api("/api/auth/logout", { method: "POST" });
      } catch (_) {
        /* 忽略 */
      }
      currentUser = null;
      renderWho();
      ratedDates.clear();
      const results = $("#results");
      if (results) {
        results.hidden = true;
        results.innerHTML = "";
      }
      setStatus("");
    });
  }

  // ---------- 当周结果渲染 ----------

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderDays(days) {
    const box = $("#results");
    if (!box) return;
    box.innerHTML = "";
    box.hidden = false;

    for (const day of days) {
      const card = el("section", "day");
      const head = el("div", "day-head");
      head.append(el("h3", null, day.date), el("span", "pill " + (GRADE[day.status] || "muted"), statusLabel(day.status)));
      card.append(head);

      if (day.status === "success" && day.items.length) {
        day.items.forEach((item, idx) => card.append(renderItem(item, idx + 1)));
      } else if (day.status === "success") {
        card.append(el("p", "day-note muted", DAY_STATUS.empty));
      } else {
        card.append(el("p", "day-note muted", DAY_STATUS[day.status] || "该日暂无数据"));
      }

      box.append(card);
      if (day.status === "success" && day.items.length) box.append(renderRatingBar(day.date));
    }
  }

  function statusLabel(status) {
    return (
      { success: "已采集", empty: "无内容", failed: "采集失败", parse_failed: "解析异常", missing: "待补采" }[status] ||
      status
    );
  }

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

  function renderItem(item, seq) {
    const wrap = el("article", "item");
    const title = el("h4", null, `${seq}. ${item.tech_name || "（未命名）"}`);
    wrap.append(title);

    wrap.append(field("技术内容", item.tech_content));
    wrap.append(field("创新点", item.innovation));

    const scen = el("div", "field");
    scen.append(el("span", "label", "应用场景"));
    const ul = el("ul", "scenarios");
    (item.scenarios || []).forEach((s) => ul.append(el("li", null, s)));
    scen.append(ul);
    wrap.append(scen);

    const meta = el("div", "meta");
    if (item.publish_date) meta.append(el("span", null, `发布时间：${item.publish_date}`));

    // 两种情况都有输出：拿不到有效链接时不留空，直接给出下一步动作
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
    wrap.append(meta);
    return wrap;
  }

  function field(label, value) {
    const box = el("div", "field");
    box.append(el("span", "label", label));
    box.append(el("p", null, value || "—"));
    return box;
  }

  /* 评分条：5 秒防抖后才发请求（§7.1） */
  function renderRatingBar(date) {
    const bar = el("div", "rating");
    if (ratedDates.has(date)) {
      bar.append(el("span", "muted", "已评分"));
      return bar;
    }
    bar.append(el("span", "rating-label", "为这一天打分："));
    const stars = el("span", "stars");
    let timer = null;
    let chosen = 0;

    for (let i = 1; i <= 5; i += 1) {
      const b = el("button", "star", "★");
      b.type = "button";
      b.dataset.score = String(i);
      b.addEventListener("click", () => {
        chosen = i;
        $$(".star", stars).forEach((s) => s.classList.toggle("on", Number(s.dataset.score) <= i));
        bar.querySelector(".rating-tip")?.remove();
        bar.append(el("span", "rating-tip muted", "已记录，5 秒后提交…"));
        clearTimeout(timer);
        timer = setTimeout(async () => {
          try {
            await apiJson("/api/rating", { method: "POST", body: { date, score: chosen } });
            ratedDates.add(date);
            bar.innerHTML = "";
            bar.append(el("span", "muted", `已评分 ${chosen} 星`));
          } catch (err) {
            bar.querySelector(".rating-tip")?.remove();
            bar.append(el("span", "rating-tip bad", err.message));
          }
        }, 5000);
      });
      stars.append(b);
    }
    bar.append(stars);
    return bar;
  }

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
        askLogin(); // 已知未登录：直接弹窗，计时器一次都不启动
        return;
      }

      stopTicker = startWaitTicker();
      const data = await apiJson("/api/weekly");
      renderDays(data.days);

      const range = `${data.range.from} ~ ${data.range.to}`;
      // 补采天数只对管理员有意义：普通用户只关心「看到什么」，不关心后台采了几次
      const extra =
        PAGE === "admin" && data.collected_now?.length
          ? `，本次补采 ${data.collected_now.length} 天`
          : "";
      const failed = data.days.filter((d) => d.status === "failed").length;
      const warn = failed ? `；${failed} 天采集失败，稍后重试即可自动补采` : "";
      setStatus(`已采集 ${range}${extra}${warn}`, failed ? "" : "good");
    } catch (err) {
      if (err.status === 401) {
        // 会话中途失效（例如在另一个标签页退出登录）：先停计时器、清掉残留的
        // 等待文案，再弹窗。只停表不清屏的话，登录框背后会一直挂着
        // 「正在获取当周数据…已等待 N 秒」，看起来像还在跑（Spec2 §8.4）。
        stopTicker?.();
        stopTicker = null;
        setStatus("");
        askLogin();
        return;
      }
      setStatus(err.message, "bad");
    } finally {
      stopTicker?.();
      if (btn) btn.disabled = false;
    }
  }

  // ---------- 管理端 ----------

  function wireTabs() {
    const tabs = $$(".tab");
    if (!tabs.length) return;
    tabs.forEach((tab) =>
      tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.toggle("active", t === tab));
        $("#tab-main").hidden = tab.dataset.tab !== "main";
        $("#tab-data").hidden = tab.dataset.tab !== "data";
        if (tab.dataset.tab === "data") refreshAdminData();
      })
    );
  }

  async function refreshAdminData() {
    await Promise.all([loadUsers(), loadSites(), loadEvalSet()]);
  }

  async function loadUsers() {
    const tbody = $("#users-table tbody");
    if (!tbody) return;
    try {
      const users = await withAuth(() => apiJson("/api/admin/users"));
      if (!users) return;
      tbody.innerHTML = "";
      for (const u of users) {
        const tr = el("tr");
        tr.append(
          el("td", null, String(u.id)),
          el("td", null, u.email),
          el("td", null, u.role === "admin" ? "管理员" : "普通用户"),
          el("td", null, u.password_masked),
          el("td", null, String(u.call_count)),
          el("td", null, u.avg_score === null ? "—" : String(u.avg_score)),
          el("td", null, String(u.rating_count)),
          el("td", null, u.created_at)
        );
        // .ops 带 white-space: nowrap —— 文案从 2 字变 4 字后，窄列里会折行
        const ops = el("td", "ops");
        const btn = el("button", "ghost", "查看密码");
        btn.addEventListener("click", async () => {
          try {
            const data = await apiJson(`/api/admin/users/${u.id}/password`);
            tr.querySelector("td:nth-child(4)").textContent = data.password;
          } catch (err) {
            alert(err.message);
          }
        });
        ops.append(btn);
        tr.append(ops);
        tbody.append(tr);
      }
    } catch (err) {
      tbody.innerHTML = "";
      tbody.append(rowWith(el("td", "bad", err.message), 9));
    }
  }

  async function loadSites() {
    const tbody = $("#sites-table tbody");
    if (!tbody) return;
    try {
      const sites = await withAuth(() => apiJson("/api/admin/sites"));
      if (!sites) return;
      tbody.innerHTML = "";
      for (const s of sites) {
        const tr = el("tr");
        tr.append(el("td", null, String(s.id)), el("td", null, s.url));

        const toggleCell = el("td");
        const toggle = el("input");
        toggle.type = "checkbox";
        toggle.checked = !!s.enabled;
        toggle.addEventListener("change", async () => {
          try {
            await apiJson(`/api/admin/sites/${s.id}`, {
              method: "PUT",
              body: { enabled: toggle.checked ? 1 : 0 },
            });
          } catch (err) {
            toggle.checked = !toggle.checked;
            alert(err.message);
          }
        });
        toggleCell.append(toggle);
        tr.append(toggleCell);

        const ops = el("td", "ops");
        const del = el("button", "ghost danger", "删除");
        del.addEventListener("click", async () => {
          if (!confirm(`删除 ${s.url}？`)) return;
          try {
            await api(`/api/admin/sites/${s.id}`, { method: "DELETE" });
            await loadSites();
          } catch (err) {
            alert(err.message);
          }
        });
        ops.append(del);
        tr.append(ops);
        tbody.append(tr);
      }
    } catch (err) {
      tbody.innerHTML = "";
      tbody.append(rowWith(el("td", "bad", err.message), 4));
    }
  }

  async function loadEvalSet() {
    const tbody = $("#eval-table tbody");
    if (!tbody) return;
    try {
      const rows = await withAuth(() => apiJson("/api/admin/eval-set"));
      if (!rows) return;
      tbody.innerHTML = "";
      if (!rows.length) {
        tbody.append(rowWith(el("td", "muted", "暂无回填记录"), 3));
        return;
      }
      for (const r of rows) {
        const tr = el("tr");
        const promptCell = el("td", "prompt-cell", r.prompt);
        tr.append(el("td", null, r.date), promptCell, el("td", null, r.created_at));
        tbody.append(tr);
      }
    } catch (err) {
      tbody.innerHTML = "";
      tbody.append(rowWith(el("td", "bad", err.message), 3));
    }
  }

  function rowWith(cell, span) {
    const tr = el("tr");
    cell.colSpan = span;
    tr.append(cell);
    return tr;
  }

  function wireAdmin() {
    const dateInput = $("#collect-date");
    if (dateInput) {
      const now = new Date();
      const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
      dateInput.value = local.toISOString().slice(0, 10);
    }

    $("#btn-collect")?.addEventListener("click", async () => {
      const date = $("#collect-date").value;
      const force = $("#collect-force").checked;
      if (!date) return setStatus("请先选择日期", "bad");
      const btn = $("#btn-collect");
      btn.disabled = true;
      setStatus(`正在采集 ${date}${force ? "（强制刷新）" : ""}…`);
      try {
        const data = await withAuth(() =>
          apiJson("/api/admin/collect", { method: "POST", body: { date, force } })
        );
        if (!data) return;
        setStatus(
          `${data.date}：${statusLabel(data.status)}，${data.item_count} 条，花费 ¥${Number(data.cost_cny).toFixed(4)}`,
          data.status === "success" ? "good" : "bad"
        );
      } catch (err) {
        setStatus(err.message, "bad");
      } finally {
        btn.disabled = false;
      }
    });

    $("#btn-add-site")?.addEventListener("click", async () => {
      const input = $("#site-url");
      const url = input.value.trim();
      if (!url) return alert("请填写 URL");
      try {
        await apiJson("/api/admin/sites", { method: "POST", body: { url } });
        input.value = "";
        await loadSites();
      } catch (err) {
        alert(err.message);
      }
    });

    $("#btn-refresh-users")?.addEventListener("click", loadUsers);
    $("#btn-refresh-eval")?.addEventListener("click", loadEvalSet);
  }

  // ---------- 启动 ----------

  async function boot() {
    wireAuthDialog();
    wireTabs();
    await loadMe();

    $("#btn-weekly")?.addEventListener("click", loadWeekly);

    if (PAGE === "admin") {
      wireAdmin();
      // 管理端进入即校验身份：未登录或非管理员则弹登录框
      if (!currentUser) {
        pendingAfterLogin = async () => {
          await refreshAdminData();
        };
        openAuth("view-login");
      } else if (currentUser.role !== "admin") {
        setStatus("当前账号不是管理员，无法使用管理功能", "bad");
      }
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
