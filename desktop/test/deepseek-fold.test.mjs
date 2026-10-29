// DeepSeek 视图的纯逻辑测试（不需要浏览器、不需要 Tauri）。
//
// 这两段判断都出过真事，所以钉在这里：
//   1. 「读不到」被写成「未登录」—— 网关开着时它独占 cookie 库，识别读不到，
//      于是一个正在应答的号在面板上显示成「未知账号 未登录」（2026-10-29 截图）。
//   2. 一个号的多份存档被平铺成多个号 —— 五个条目背后只有两个人。
import test from "node:test";
import assert from "node:assert/strict";
import { foldAccounts, leadRank, loginStateOf, unreadableNames } from "../src/deepseek-fold.js";

// ---------------------------------------------------------------- 三态

test("the new three-state field is taken as given", () => {
  assert.equal(loginStateOf({ loginState: "signed-in", loggedIn: true }), "signed-in");
  assert.equal(loginStateOf({ loginState: "signed-out", loggedIn: false }), "signed-out");
  assert.equal(loginStateOf({ loginState: "unknown", loggedIn: false }), "unknown");
});

// 面板先装、CLI 后升级（或反过来）时，不能因为少一个字段就退回二态。
test("an older CLI payload still cannot turn an unreadable profile into a signed-out one", () => {
  assert.equal(loginStateOf({ loggedIn: false, readable: false }), "unknown",
    "readable=false 是「没读到」，不是「没人登录」");
  assert.equal(loginStateOf({ loggedIn: false, readable: true }), "signed-out",
    "读得到而且没证据，才是真的未登录");
  assert.equal(loginStateOf({ loggedIn: false }), "signed-out",
    "连 readable 都没有的旧输出按旧语义处理");
});

test("evidence that was read outranks a file that could not be", () => {
  assert.equal(loginStateOf({ loggedIn: true, readable: false }), "signed-in",
    "读到的 token 不会被读不到的文件推翻");
});

test("the unreadable file is named, not implied", () => {
  assert.equal(
    unreadableNames({ unreadable: [{ entry: "Default/Network/Cookies", code: "EBUSY" }] }, "、"),
    "Default/Network/Cookies"
  );
  assert.equal(
    unreadableNames({ unreadable: [{ entry: "a" }, { entry: "b" }] }, "、"),
    "a、b"
  );
  assert.equal(unreadableNames({}), "Default/Network/Cookies", "什么都没给时退回那个最常见的");
});

// ---------------------------------------------------------------- 折叠

const manual = { name: "137-v3", group: "token:aaa", loggedIn: true, loginState: "signed-in", auto: false };
const autoCopy = { name: "auto-unknown-2026-10-28T17-45-06", group: "token:aaa", loggedIn: true,
  loginState: "signed-in", auto: true, savedAt: "2026-10-28T17:45:06Z" };
const other = { name: "17276613640", group: "phone:bbb", loggedIn: true, loginState: "signed-in",
  auto: false, inUse: true, phones: ["172****3640"] };

test("copies of one account are folded into one row", () => {
  const groups = foldAccounts([manual, autoCopy, other]);
  assert.equal(groups.length, 2, "两个号，两组");
  assert.equal(groups[0].lead.name, "17276613640", "在用的那组排最前");
  const same = groups.find((g) => g.key === "token:aaa");
  assert.equal(same.members.length, 2, "两份都留在组里，展开能看见");
  assert.equal(same.lead.name, "137-v3", "人工命名的当代表，自动存档不抢主位");
});

test("a pool that is all auto snapshots still shows the newest as the row", () => {
  const groups = foldAccounts([
    { ...autoCopy, name: "auto-1", savedAt: "2026-10-28T01:00:00Z" },
    { ...autoCopy, name: "auto-2", savedAt: "2026-10-28T05:00:00Z" },
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].lead.name, "auto-2");
});

// 折叠的前提是"确定是同一个人"。后端没给 group 时（旧版 CLI）宁可多一行，
// 也不能把两个号折成一个 —— 那会让"换号"指向错的存档。
test("without a group field nothing is folded", () => {
  const groups = foldAccounts([{ name: "a", loggedIn: true }, { name: "b", loggedIn: true }]);
  assert.equal(groups.length, 2);
});

// 后台每 5 秒重渲染一次：顺序若依赖输入顺序，刚展开的那组会自己跳走。
test("group order does not depend on the order the backend listed them", () => {
  const forward = foldAccounts([manual, autoCopy, other]).map((g) => g.lead.name).join(",");
  const backward = foldAccounts([other, autoCopy, manual]).map((g) => g.lead.name).join(",");
  assert.equal(forward, backward);
});

test("ranking prefers what a person would pick", () => {
  assert.ok(leadRank({ inUse: true, name: "x" }) > leadRank({ auto: false, name: "y" }));
  assert.ok(leadRank({ auto: false }) > leadRank({ auto: true }), "人工存档优先于自动存档");
  assert.ok(leadRank({ loginState: "signed-in" }) > leadRank({ loginState: "signed-out" }));
  assert.ok(leadRank({ phones: ["172****3640"] }) > leadRank({ phones: [] }));
});
