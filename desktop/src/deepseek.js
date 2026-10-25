// DeepSeek 网关界面：账号池（保存 / 换号 / 移除）+ 网关启停。
//
// 与另两个视图的关系：同一窗口里的第三个「页签」，共用顶栏与样式。
// 后端不走 Python 侧车，而是 Rust 直接跑网关仓库里的 Node CLI
// （见 src-tauri/src/deepseek.rs）—— 换号内核只有一份，在网关仓库里。
//
// 稳定性约定（与 workbuddy.js 一致）：
//   1. 所有会失败的操作都走 `call()`，统一捕错并弹提示，不产生未处理 rejection；
//   2. 操作期间置 busy，按钮禁用，避免重复点击；
//   3. 后端字段可能缺失（不同版本 CLI），渲染一律兜底。
import { invoke } from "@tauri-apps/api/core";
import { esc, toast, openConfirmModal, toggleTheme as flipTheme, themeBtnHtml } from "./ui.js";
import { ic } from "./icons.js";
import { t } from "./i18n.js";

// ---------------------------------------------------------------- 模块状态

/** `ds_state` 的返回。 */
let state = null;
/** 当前进行中的操作名（用于禁用按钮与显示忙锁条）。 */
let busy = "";
/** 是否展开「保存当前账号」的输入框。 */
let capturing = false;
/** 登录窗口是否已开出去（用于显示「登完关窗口再保存」的提示）。 */
let loginOpened = false;
/** 最近一次错误信息（null 表示无）。 */
let failure = null;

/** 重新渲染由 main.js 注入，避免模块互相 import 成环。 */
let rerender = () => {};

export function bindRerender(fn) {
  rerender = typeof fn === "function" ? fn : () => {};
}

// ---------------------------------------------------------------- 调用封装

/** 统一处理忙碌与错误：失败弹 toast 并返回 undefined（不抛异常）。 */
async function call(label, fn) {
  if (busy) return undefined;
  busy = label;
  failure = null;
  rerender();
  try {
    return await fn();
  } catch (e) {
    failure = String(e);
    toast(String(e), "err");
    console.warn("[DeepSeek] failed:", e);
    return undefined;
  } finally {
    busy = "";
    rerender();
  }
}

export async function refresh() {
  try {
    state = await invoke("ds_state");
  } catch (e) {
    state = null;
    failure = String(e);
    console.warn("[DeepSeek] ds_state failed:", e);
  }
  rerender();
}

// ---------------------------------------------------------------- 渲染

function btn(label, icon, handler, { disabled = false, kind = "ghost" } = {}) {
  return `<button class="${kind === "primary" ? "btn-primary" : "btn-ghost"} has-ic"
    click="${handler}" ${disabled ? "disabled" : ""}>${icon ? ic(icon, 16) + " " : ""}${esc(label)}</button>`;
}

/** 网关状态一行：端口、是否在跑、版本。数据缺失时说「未知」而不是编造。 */
function gatewayLine() {
  const g = state?.gateway || {};
  if (g.error) return `<div class="wb-note err">${esc(g.error)}</div>`;
  const dot = g.listening ? "run" : "off";
  const text = g.listening
    ? t("ds.gw.running", { port: g.port ?? "?" })
    : t("ds.gw.stopped", { port: g.port ?? "?" });
  const ver = g.version ? ` · ${esc(g.version)}` : "";
  return `<div class="ds-line">
    <span class="status-dot ${dot}"></span>
    <span class="status-text">${esc(text)}${ver}</span>
  </div>`;
}

/** 当前登录是谁（六文件在位情况 + 打码手机号）。 */
function currentLine() {
  const c = state?.current || {};
  if (c.error) return `<div class="wb-note err">${esc(c.error)}</div>`;
  if (c.exists === false) return `<div class="ds-line">${esc(t("ds.noProfile"))}</div>`;
  const who = (c.phones || []).join(", ") || t("ds.unknownAccount");
  return `<div class="ds-line">${esc(t("ds.signedInAs", { who }))}
    <span class="count">${esc(t("ds.entries", { n: c.entriesPresent ?? 0, total: c.entriesExpected ?? 6 }))}</span></div>`;
}

function rowHtml(a) {
  const who = (a.phones || []).join(", ") || t("ds.unknownAccount");
  const when = a.savedAt ? String(a.savedAt).slice(0, 16).replace("T", " ") : "?";
  // CLI 给的是字节数（快照是六文件，通常几 MB），这里换算成 MB 显示。
  const size = Number.isFinite(a.size) ? `${(a.size / 1024 / 1024).toFixed(1)} MB` : "";
  return `
  <div class="row" data-name="${esc(a.name)}">
    <div class="row-top">
      <span class="notch" style="background:var(--notch-3)"></span>
      <div class="row-main">
        <div class="row-name">${esc(a.name)}</div>
        <div class="row-meta">${esc(who)}${size ? " · " + esc(size) : ""} · ${esc(when)}</div>
      </div>
      <div class="row-actions">
        <button class="icon-btn danger" title="${esc(t("ds.drop"))}" aria-label="${esc(t("ds.drop"))}"
          click="dsActions.askDrop('${esc(a.name)}')" ${busy ? "disabled" : ""}>${ic("x", 16)}</button>
        <button class="btn-switch has-ic" click="dsActions.askSwitch('${esc(a.name)}')" ${busy ? "disabled" : ""}>
          ${ic("swap", 14)} ${esc(t("ds.switch"))}
        </button>
      </div>
    </div>
  </div>`;
}

function setupHtml() {
  return `<div class="wb-wrap">
    <div class="empty">
      <div class="glyph">${ic("sliders", 34)}</div>
      ${esc(state?.hint || t("ds.hint"))}
    </div>
    <section class="toolbar">
      ${btn(t("ds.pickDir"), "sliders", "dsActions.pickGatewayDir()", { kind: "primary" })}
      ${btn(t("ds.pickNode"), "userPlus", "dsActions.pickNode()")}
    </section>
    ${nodeLine()}
  </div>`;
}

function nodeLine() {
  const n = state?.node || {};
  const ok = n.ok ? t("ds.nodeOk", { v: n.version || "" }) : t("ds.nodeBad", { e: n.detail || "?" });
  return `<div class="ds-line">${esc(t("ds.node", { path: n.path || "node" }))} — ${esc(ok)}</div>`;
}

export function viewHtml(tabsHtml) {
  const header = `
  <header class="topbar">
    <div class="wordmark">SwitchSuite</div>
    ${tabsHtml}
    <div class="top-end">
      ${themeBtnHtml("dsActions.toggleTheme()")}
    </div>
  </header>`;

  if (!state) {
    return header + `<main class="list"><div class="wb-wrap"><div class="loading">LOADING</div></div></main>`;
  }
  if (!state.found) return header + `<main class="list">${setupHtml()}</main>`;

  const accounts = state.accounts?.accounts || [];
  const listHtml = accounts.length
    ? accounts.map(rowHtml).join("")
    : `<div class="empty">
         <div class="glyph">${ic("empty", 34)}</div>
         ${esc(t("ds.emptyTitle"))}<br>${esc(t("ds.emptyBody"))}
       </div>`;

  const busyBar = busy
    ? `<div class="wb-note"><span class="spinner"></span><span>${esc(t("ds.working", { what: busyLabel(busy) }))}</span></div>`
    : "";

  const captureBox = capturing
    ? `<div class="ds-capture">
         <input class="rename-input" id="ds-capture-input" maxlength="48" placeholder="${esc(t("ds.namePh"))}"
           keydown="onDsCaptureKey(event)" blur="dsActions.cancelCapture()">
         <button class="btn-primary" click="dsActions.doCapture()">${esc(t("common.save"))}</button>
       </div>`
    : "";

  const toolbar = `
  <section class="toolbar">
    ${btn(t("ds.login"), "userPlus", "dsActions.askLogin()", { disabled: !!busy, kind: "primary" })}
    ${btn(t("ds.saveLogin"), "capture", "dsActions.capture()", { disabled: !!busy })}
    <span class="tb-spacer"></span>
    ${btn(t("ds.gwStart"), "play", "dsActions.gateway('start')", { disabled: !!busy })}
    ${btn(t("ds.gwStop"), "power", "dsActions.gateway('stop')", { disabled: !!busy })}
    ${btn(t("ds.gwRestart"), "refresh", "dsActions.gateway('restart')", { disabled: !!busy })}
    ${btn(t("common.refresh"), "refresh", "dsActions.reload()", { disabled: !!busy })}
  </section>`;

  return header + `
  <main class="list wb-list">
    <div class="wb-wrap">
      ${busyBar}
      ${failure ? `<div class="wb-note err">${esc(failure)}</div>` : ""}
      ${loginOpened ? `<div class="wb-note">${esc(t("ds.loginHint"))}</div>` : ""}
      ${toolbar}
      ${captureBox}
      ${gatewayLine()}
      ${currentLine()}
      ${nodeLine()}
      <div class="section-head">
        <h2>${esc(t("ds.accountsTitle"))}</h2>
        <span class="count">${accounts.length}</span>
      </div>
      ${listHtml}
      <div class="wb-foot">${esc(state.dir || "")}</div>
    </div>
  </main>`;
}

function busyLabel(key) {
  const map = {
    switch: t("ds.opSwitch"),
    capture: t("ds.opCapture"),
    drop: t("ds.opDrop"),
    gateway: t("ds.opGateway"),
    login: t("ds.opLogin"),
    refresh: t("ds.opRefresh"),
  };
  return map[key] || key;
}

/** 离开视图时的清理：收起输入框，避免下次进来还是展开的。 */
export function onLeave() {
  capturing = false;
  loginOpened = false;
}

// ---------------------------------------------------------------- 交互

export const dsActions = {
  async reload() {
    await call("refresh", () => refresh());
  },

  toggleTheme() {
    flipTheme();
    rerender();
  },

  /** 登录要先停网关（同一个 profile 被 Chromium 独占），所以要人确认一次。 */
  askLogin() {
    openConfirmModal({
      kind: "warn",
      icon: "userPlus",
      title: t("ds.loginConfirmTitle"),
      desc: t("ds.loginConfirmDesc"),
      yesLabel: t("ds.login"),
      onYes: () => dsActions.login(),
    });
  },

  async login() {
    const r = await call("login", () => invoke("ds_login"));
    if (!r) return;
    loginOpened = true;
    toast(t("ds.toastLogin"), "ok", t("ds.toastLoginDetail"));
    await refresh();
  },

  capture() {
    capturing = true;
    rerender();
    document.getElementById("ds-capture-input")?.focus();
  },

  cancelCapture() {
    if (window.__dsCaptureSaving) return;
    capturing = false;
    rerender();
  },

  async doCapture() {
    const input = document.getElementById("ds-capture-input");
    const name = (input?.value || "").trim();
    if (!name) return;
    window.__dsCaptureSaving = true;
    await call("capture", async () => {
      await invoke("ds_capture", { name });
      // 快照成功即说明浏览器已经放手（否则会被锁检测挡下），提示可以收了。
      loginOpened = false;
      toast(t("ds.toastSaved", { name }), "ok");
    });
    window.__dsCaptureSaving = false;
    capturing = false;
    await refresh();
  },

  /** 换号会停网关再起网关 —— 这一步要让人确认，不是点一下就改的。 */
  askSwitch(name) {
    openConfirmModal({
      title: t("ds.confirmSwitchTitle"),
      desc: t("ds.confirmSwitchDesc", { name }),
      kind: "warn",
      icon: "swap",
      yesLabel: t("ds.switch"),
      onYes: () => dsActions.switchTo(name),
    });
  },

  async switchTo(name) {
    const r = await call("switch", () => invoke("ds_switch", { name }));
    if (!r) return;
    const started = r.started || {};
    if (started.error) {
      toast(t("ds.swapOkStartFailed"), "warn", String(started.error));
    } else if (started.started === false && started.alreadyRunning) {
      toast(t("ds.alreadyRunning"), "warn");
    } else {
      toast(t("ds.toastSwitched", { name }), "ok");
    }
    await refresh();
  },

  askDrop(name) {
    openConfirmModal({
      title: t("ds.confirmDropTitle"),
      desc: t("ds.confirmDropDesc", { name }),
      kind: "danger",
      icon: "x",
      yesLabel: t("common.delete"),
      onYes: () => dsActions.drop(name),
    });
  },

  async drop(name) {
    const r = await call("drop", () => invoke("ds_drop", { name }));
    if (!r) return;
    toast(t("ds.toastDropped", { name }), "ok", t("ds.toastDroppedDetail"));
    await refresh();
  },

  async gateway(action) {
    const r = await call("gateway", () => invoke("ds_gateway", { action }));
    if (!r) return;
    if (action === "stop") toast(t("ds.toastStopped"), "ok");
    if (action === "start") toast(r?.started ? t("ds.toastStarted") : t("ds.startFailed"), r?.started ? "ok" : "warn");
    if (action === "restart") toast(t("ds.toastRestarted"), "ok");
    await refresh();
  },

  async pickGatewayDir() {
    const picked = await call("gateway", () => invoke("ds_pick_gateway_dir"));
    if (!picked || !picked.picked) return;
    await call("gateway", () => invoke("ds_set_gateway_dir", { path: picked.path }));
    toast(picked.hasCli ? t("ds.dirSet") : t("ds.dirNoCli"), picked.hasCli ? "ok" : "warn");
    await refresh();
  },

  async pickNode() {
    const picked = await call("gateway", () => invoke("ds_pick_node"));
    if (!picked || !picked.picked) return;
    await call("gateway", () => invoke("ds_set_node_path", { path: picked.path }));
    await refresh();
  },
};

/** 输入框回车提交（Esc 取消）。 */
export function onDsCaptureKey(event) {
  if (event.key === "Enter") {
    event.preventDefault();
    dsActions.doCapture();
  } else if (event.key === "Escape") {
    dsActions.cancelCapture();
  }
}

window.dsActions = dsActions;
window.onDsCaptureKey = onDsCaptureKey;
