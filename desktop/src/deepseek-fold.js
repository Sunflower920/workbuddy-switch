// DeepSeek 视图的纯逻辑：登录三态 + 「一个号的 N 份存档」怎么折。
//
// 单独成一个文件，理由只有一个：它能被 Node 直接测。deepseek.js 依赖
// @tauri-apps/api 与 DOM，渲染函数在测试里跑不起来；而下面这两段判断恰好是
// 界面最容易说谎的地方 —— 「读不到」被说成「没登录」，「一个人」被显示成五个号。
// 都出过真事，所以它们不该只活在一个没人能测的渲染函数里。
//
// 这个文件不 import 任何东西（连 i18n 都不），保持可测。

/**
 * 登录状态取三态：signed-in / signed-out / unknown。
 *
 * 第三态不是凑数。网关运行时会独占 profile 的 cookie 库（Windows 给 EBUSY），
 * 识别读不到它，于是「没读到证据」被打印成「没有登录」—— 2026-10-29 面板就这么
 * 把一个正在通过网关应答的号显示成「未知账号 未登录」。
 *
 * 新版本 CLI 直接给 loginState；旧版只有 loggedIn/readable，按证据降级判断，
 * 免得面板和 CLI 版本错开时又退回到二态。
 */
export function loginStateOf(info) {
  const given = info?.loginState;
  if (given === "signed-in" || given === "signed-out" || given === "unknown") return given;
  if (info?.loggedIn) return "signed-in";
  return info?.readable === false ? "unknown" : "signed-out";
}

/**
 * 读不到哪个文件。说出来才是可诊断的；只说「读不到」等于什么都没说。
 * `sep` 由调用方给（中文顿号 / 英文逗号），这里不碰 i18n。
 */
export function unreadableNames(info, sep = ", ") {
  const names = (info?.unreadable || []).map((item) => item?.entry).filter(Boolean);
  return names.length ? names.join(sep) : "Default/Network/Cookies";
}

/** 组里拿谁当代表：在用的 > 人工命名的 > 已登录的 > 有手机号的。 */
export function leadRank(a) {
  return (a.inUse ? 8 : 0)
    + (a.auto ? 0 : 4)
    + (loginStateOf(a) === "signed-in" ? 2 : 0)
    + ((a.phones || []).length ? 1 : 0);
}

/**
 * 同一个号的 N 份存档折成一组。
 *
 * 后端用并查集把 userId / phone / token 三种键串成 `group`：同一个号重新登录会
 * 换 token，只比一项会把一个人认成两个；而不同存档能拿到的键还不一样（有的只有
 * 账号 id、有的只有手机号）。这些后端一直算着，面板一个字段都没读，直接平铺 ——
 * 五个条目背后只有两个人，列表比账号还长。
 *
 * 返回 [{ key, members, lead }]，顺序稳定：在用的那组最前，其余按代表项名字。
 */
export function foldAccounts(accounts) {
  const byGroup = new Map();
  for (const account of accounts || []) {
    // 旧版 CLI 没有 group：各成一组。宁可不折叠，也不能把两个号折成一个。
    const key = account.group || `name:${account.name}`;
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key).push(account);
  }
  const out = [];
  for (const [key, members] of byGroup) {
    // 依次比：代表分高的在前；同分时新的存档在前 —— 自动存档是退路，不是主号。
    const sorted = members.slice().sort((a, b) => leadRank(b) - leadRank(a)
      || String(b.savedAt || "").localeCompare(String(a.savedAt || "")));
    out.push({ key, members: sorted, lead: sorted[0] });
  }
  // 顺序必须与输入顺序无关，否则每隔 5 秒的后台重渲染会让列表自己跳位，
  // 刚点开的那一组跑到别处去。
  out.sort((a, b) => (b.lead.inUse ? 1 : 0) - (a.lead.inUse ? 1 : 0)
    || String(a.lead.name).localeCompare(String(b.lead.name)));
  return out;
}
