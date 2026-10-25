//! DeepSeek 网关账号（第三个域）。
//!
//! 这里刻意不做“换号”本身。换号的内核在网关仓库自己的 CLI 里
//! （`tools/account-pool.mjs`，六文件原子交换 + 锁检测 + 路径穿越防护，
//! 有测试覆盖；`tools/gateway-ctl.mjs` 管启停）。本模块只做三件事：
//! 找到那两个 CLI，把它们跑起来，把 JSON 信封转成界面能用的形状。
//!
//! 为什么不在 Rust 里重写：
//!   1. “什么是一个登录”已经有一份真源（六文件清单），重写就会出现第二份，
//!      而两份清单迟早不一致；
//!   2. 停网关要先验明正身（先看匿名 /health 的形状，才带密钥要求详细体），
//!      这套校验在 stop-gateway.ps1 里且经过审计 —— 换个语言重写的版本没有。
//!
//! CLI 只在 stdout 说 JSON（连拒绝也说），所以这里不必解析任何散文。

use crate::i18n::{tr, trf};
use crate::store::{load_settings, no_window, save_settings, Paths, Settings};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tauri_plugin_dialog::DialogExt;

const ACCOUNT_CLI: &str = "tools/account-pool.mjs";
const GATEWAY_CLI: &str = "tools/gateway-ctl.mjs";

/// 列表/查询类：纯本地文件读取，几秒内必有答案。
const QUICK_TIMEOUT_SECS: u64 = 40;
/// 切号 + 停网关 + 起网关 + 等 /health：网关要开浏览器，慢是正常的。
const SWITCH_TIMEOUT_SECS: u64 = 180;

// ---------------------------------------------------------------- 路径

fn settings() -> Settings {
    let paths = Paths::detect();
    load_settings(&paths)
}

fn cli_at(dir: &Path) -> bool {
    dir.join(ACCOUNT_CLI).is_file()
}

/// 在这些父目录下各看一层，找含 account-pool.mjs 的子目录。
///
/// 只扫一层：网关仓库是个目录，不是散落的文件，一层足够且开销可忽略。
/// 顺序上用户的设置优先，环境变量其次，最后是几个常见落点 —— 后者只是
/// “帮你先猜一个”，猜错了界面上可以改，猜对了省一次选择。
fn scan_parent(parent: &Path) -> Option<PathBuf> {
    if cli_at(parent) {
        return Some(parent.to_path_buf());
    }
    let mut found: Option<PathBuf> = None;
    for entry in fs::read_dir(parent).ok()?.flatten() {
        let p = entry.path();
        if p.is_dir() && cli_at(&p) {
            found = Some(p);
        }
    }
    found
}

fn scan_roots() -> Vec<PathBuf> {
    let home = Paths::detect().home;
    let mut roots = Vec::new();
    if let Ok(p) = std::env::var("DSW_GATEWAY_HOME") {
        if !p.trim().is_empty() {
            roots.push(PathBuf::from(p));
        }
    }
    roots.push(PathBuf::from(r"D:\Program Files\Deepseek Desktop"));
    roots.push(home.clone());
    roots
}

/// 网关目录：设置 > 环境变量 > 扫描。找不到不算错误 —— 界面要给出
/// “请选择网关目录”，而不是一个红字报错。
fn gateway_dir(s: &Settings) -> Option<PathBuf> {
    let configured = s
        .ds_gateway_dir
        .as_deref()
        .map(str::trim)
        .filter(|p| !p.is_empty());
    if let Some(p) = configured {
        let d = PathBuf::from(p);
        if cli_at(&d) {
            return Some(d);
        }
    }
    if let Ok(p) = std::env::var("DSW_GATEWAY_DIR") {
        if !p.trim().is_empty() {
            let d = PathBuf::from(p);
            if cli_at(&d) {
                return Some(d);
            }
        }
    }
    scan_roots().iter().find_map(|root| scan_parent(root))
}

fn node_exe(s: &Settings) -> String {
    s.ds_node_path
        .as_deref()
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .map(String::from)
        .or_else(|| std::env::var("DSW_NODE_PATH").ok().filter(|p| !p.trim().is_empty()))
        .unwrap_or_else(|| "node".to_string())
}

// ---------------------------------------------------------------- 执行

/// 跑一个 CLI 并解信封。
///
/// 信封永远在 stdout（见 CLI 里的说明），所以退出码只看成败、不看内容：
/// 真正要展示给人的话在 `error` 字段里，已经是最终文案。
fn run_cli(dir: &Path, node: &str, rel: &str, args: &[String]) -> Result<Value, String> {
    let script = dir.join(rel);
    let out = no_window(node)
        .arg(&script)
        .args(args)
        .current_dir(dir)
        .output()
        .map_err(|e| trf("ds.err.spawn", &[("e", &e.to_string())]))?;

    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();

    if stdout.is_empty() {
        return Err(if stderr.is_empty() {
            trf("ds.err.noOutput", &[("code", &out.status.code().map(|c| c.to_string()).unwrap_or("?".into()))])
        } else {
            stderr
        });
    }

    let envelope: Value =
        serde_json::from_str(&stdout).map_err(|e| trf("ds.err.badJson", &[("e", &e.to_string())]))?;
    let ok = envelope.get("ok").and_then(Value::as_bool).unwrap_or(false);
    if !ok {
        let message = envelope
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or_else(|| "")
            .to_string();
        return Err(if message.is_empty() { tr("ds.err.unknown") } else { message });
    }
    Ok(envelope.get("data").cloned().unwrap_or(Value::Null))
}

/// 子进程是阻塞的，所以丢到阻塞线程池，外面再套一层超时 —— 否则一个卡住的
/// CLI 会让界面一直转圈，而不是告诉用户卡在哪一步。
async fn run_cli_async(
    dir: PathBuf,
    node: String,
    rel: &'static str,
    args: Vec<String>,
    timeout_secs: u64,
) -> Result<Value, String> {
    let handle = tauri::async_runtime::spawn_blocking(move || run_cli(&dir, &node, rel, &args));
    match tokio::time::timeout(Duration::from_secs(timeout_secs), handle).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => Err(tr("ds.err.join")),
        Err(_) => Err(trf("ds.err.timeout", &[("s", &timeout_secs.to_string())])),
    }
}

/// 把目录和 node 一起解出来；目录缺失是界面要处理的一种状态，不是错误。
fn resolved() -> (Option<PathBuf>, String) {
    let s = settings();
    let dir = gateway_dir(&s);
    let node = node_exe(&s);
    (dir, node)
}

fn node_probe(node: &str) -> Value {
    match no_window(node).arg("-v").output() {
        Ok(out) if out.status.success() => json!({
            "path": node,
            "ok": true,
            "version": String::from_utf8_lossy(&out.stdout).trim().to_string(),
        }),
        Ok(out) => json!({
            "path": node,
            "ok": false,
            "detail": String::from_utf8_lossy(&out.stderr).trim().to_string(),
        }),
        Err(e) => json!({ "path": node, "ok": false, "detail": e.to_string() }),
    }
}

// ---------------------------------------------------------------- 命令

/// 面板总览：网关在哪里、node 能不能用、有哪些账号、当前登录是谁、网关在不在跑。
#[tauri::command]
pub async fn ds_state() -> Result<Value, String> {
    let (dir, node) = resolved();
    let node_info = node_probe(&node);
    let Some(dir) = dir else {
        return Ok(json!({
            "found": false,
            "node": node_info,
            "hint": tr("ds.setup.hint"),
        }));
    };

    let accounts = run_cli_async(
        dir.clone(),
        node.clone(),
        ACCOUNT_CLI,
        vec!["list".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));
    let current = run_cli_async(
        dir.clone(),
        node.clone(),
        ACCOUNT_CLI,
        vec!["current".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));
    let gateway = run_cli_async(
        dir.clone(),
        node.clone(),
        GATEWAY_CLI,
        vec!["status".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));

    Ok(json!({
        "found": true,
        "dir": dir.to_string_lossy(),
        "node": node_info,
        "accounts": accounts,
        "current": current,
        "gateway": gateway,
    }))
}

/// 把当前登录存成账号。名字交给 CLI 校验（它会变成目录名）。
///
/// 存档要独占 profile：浏览器还开着时，复制出来的 Cookie 数据库是坏的
/// （会"保存成功"却登不进去），所以 CLI 会拒绝。这个拒绝是对的，但把
/// "你自己先去点停止网关，存完再点启动"留给用户是没必要的 —— 网关照停、
/// 存完照起，恢复到点之前的原样。只有一种情况仍需人动手：另有登录窗口
/// 开着（那是人手开的窗口，不该由这里关掉），此时给出明确的说法。
#[tauri::command]
pub async fn ds_capture(name: String) -> Result<Value, String> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(tr("ds.err.nameEmpty"));
    }
    let (dir, node) = resolved();
    let Some(dir) = dir else { return Err(tr("ds.err.noDir")) };

    let status = run_cli_async(
        dir.clone(),
        node.clone(),
        GATEWAY_CLI,
        vec!["status".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|_| json!({}));
    let was_running = status.get("listening").and_then(Value::as_bool).unwrap_or(false);

    if was_running {
        run_cli_async(
            dir.clone(),
            node.clone(),
            GATEWAY_CLI,
            vec!["stop".into(), "--json".into()],
            SWITCH_TIMEOUT_SECS,
        )
        .await
        .map_err(|e| trf("ds.err.stopFailed", &[("e", &e)]))?;
    }

    let saved = run_cli_async(
        dir.clone(),
        node.clone(),
        ACCOUNT_CLI,
        vec!["save".into(), name, "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await;

    // 无论存档成败都把网关恢复到点之前的状态：用户在别处等着的会话
    // 不该因为这次存档而一直停着。恢复失败必须说出来 —— stop-gateway.ps1
    // 会留下 data/stop-flag 压住看门狗 30 分钟，也就是说"没起来"这件事
    // 不会自己好，用户得知道要去点启动。
    let restart = if was_running {
        Some(
            run_cli_async(
                dir,
                node,
                GATEWAY_CLI,
                vec!["start".into(), "--json".into()],
                SWITCH_TIMEOUT_SECS,
            )
            .await
            .unwrap_or_else(|e| json!({ "error": e })),
        )
    } else {
        None
    };

    let saved = saved.map_err(|e| {
        if e.contains("still owned by a running browser") {
            tr("ds.err.profileBusy")
        } else {
            e
        }
    })?;

    Ok(json!({ "saved": saved, "restarted": was_running, "restart": restart }))
}

/// 切号：停网关 → 换登录态 → 起网关。
///
/// 顺序不是随意的。Chromium 独占 profile，而网关在启动时才解析 userDataDir，
/// 所以“先停再换”是硬约束；反过来做，换完的登录态会被正在退出的浏览器
/// 回写覆盖。任何一步失败就停下 —— 半途继续只会得到一个没有网关的账号。
#[tauri::command]
pub async fn ds_switch(name: String) -> Result<Value, String> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(tr("ds.err.nameEmpty"));
    }
    let (dir, node) = resolved();
    let Some(dir) = dir else { return Err(tr("ds.err.noDir")) };

    let stopped = run_cli_async(
        dir.clone(),
        node.clone(),
        GATEWAY_CLI,
        vec!["stop".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));
    if stopped.get("error").is_some() {
        return Err(trf(
            "ds.err.stopFailed",
            &[("e", stopped.get("error").and_then(Value::as_str).unwrap_or(""))],
        ));
    }

    let swapped = run_cli_async(
        dir.clone(),
        node.clone(),
        ACCOUNT_CLI,
        vec!["use".into(), name.clone(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await?;

    let started = run_cli_async(
        dir.clone(),
        node.clone(),
        GATEWAY_CLI,
        vec!["start".into(), "--json".into()],
        SWITCH_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));

    Ok(json!({ "name": name, "stopped": stopped, "swapped": swapped, "started": started }))
}

/// 登录一个新账号：停网关 → 打开网关自己的登录模式（`--login`）。
///
/// 先停是硬约束：登录窗口要用同一个 profile，而 Chromium 独占它 —— 网关还
/// 在跑时开出来的窗口会直接死在锁上（`00登录.bat` 也是这条规矩）。
/// 浏览器窗口留给 Detached 子进程，人登完自己关；关掉之后才能保存快照
/// （保存会被锁检测挡住，这是故意的：正被浏览器持有的 Cookie 复制出来是坏的）。
#[tauri::command]
pub async fn ds_login(fresh: bool) -> Result<Value, String> {
    let (dir, node) = resolved();
    let Some(dir) = dir else { return Err(tr("ds.err.noDir")) };

    let stopped = run_cli_async(
        dir.clone(),
        node.clone(),
        GATEWAY_CLI,
        vec!["stop".into(), "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
    .unwrap_or_else(|e| json!({ "error": e }));
    if stopped.get("error").is_some() {
        return Err(trf(
            "ds.err.stopFailed",
            &[("e", stopped.get("error").and_then(Value::as_str).unwrap_or(""))],
        ));
    }

    // `--fresh` = 先存档再清空登录态。不清空的话 profile 里还留着旧账号的
    // Cookie，打开的页面是那个已登录的会话而不是登录表单（`--login` 只是
    // goto(targetUrl)），窗口对“加另一个号”毫无用处。
    let mut args = vec!["login".into(), "--json".into()];
    if fresh {
        args.push("--fresh".into());
    }
    let login = run_cli_async(dir, node, GATEWAY_CLI, args, QUICK_TIMEOUT_SECS).await?;

    Ok(json!({ "stopped": stopped, "login": login }))
}

/// 移除账号（CLI 只挪到 .recycled，不真删）。
#[tauri::command]
pub async fn ds_drop(name: String) -> Result<Value, String> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(tr("ds.err.nameEmpty"));
    }
    let (dir, node) = resolved();
    let Some(dir) = dir else { return Err(tr("ds.err.noDir")) };
    run_cli_async(
        dir,
        node,
        ACCOUNT_CLI,
        vec!["drop".into(), name, "--json".into()],
        QUICK_TIMEOUT_SECS,
    )
    .await
}

/// 网关启停查询：status | start | stop | restart。
#[tauri::command]
pub async fn ds_gateway(action: String) -> Result<Value, String> {
    let action = action.trim().to_string();
    if !["status", "start", "stop", "restart"].contains(&action.as_str()) {
        return Err(tr("ds.err.badAction"));
    }
    let (dir, node) = resolved();
    let Some(dir) = dir else { return Err(tr("ds.err.noDir")) };
    let secs = if action == "status" { QUICK_TIMEOUT_SECS } else { SWITCH_TIMEOUT_SECS };
    run_cli_async(
        dir,
        node,
        GATEWAY_CLI,
        vec![action, "--json".into()],
        secs,
    )
    .await
}

/// 选网关目录：文件对话框只能选文件，所以让用户选中目录里的任一文件，取它的
/// 父目录 —— 比要求用户手打路径可靠，也避免引入文件夹选择器的新依赖路径。
#[tauri::command]
pub async fn ds_pick_gateway_dir(app: AppHandle) -> Result<Value, String> {
    let picked = app.dialog().file().blocking_pick_file();
    let Some(fp) = picked else {
        return Ok(json!({ "picked": false }));
    };
    let path = fp
        .into_path()
        .map_err(|e| trf("err.path.invalid", &[("e", &e.to_string())]))?;
    let dir = path.parent().map(|p| p.to_path_buf()).unwrap_or(path.clone());
    Ok(json!({ "picked": true, "path": dir.to_string_lossy(), "hasCli": cli_at(&dir) }))
}

#[tauri::command]
pub async fn ds_set_gateway_dir(app: AppHandle, path: String) -> Result<(), String> {
    let paths = Paths::detect();
    let mut s = settings();
    s.ds_gateway_dir = Some(path.trim().to_string()).filter(|p| !p.is_empty());
    let r = save_settings(&paths, &s);
    let _ = app.emit("state-changed", ());
    r
}

/// 选 node.exe。PATH 里已经有 node 时通常不需要这一步。
#[tauri::command]
pub async fn ds_pick_node(app: AppHandle) -> Result<Value, String> {
    let picked = app
        .dialog()
        .file()
        .add_filter(&tr("dialog.exe"), &["exe"])
        .blocking_pick_file();
    let Some(fp) = picked else {
        return Ok(json!({ "picked": false }));
    };
    let path = fp
        .into_path()
        .map_err(|e| trf("err.path.invalid", &[("e", &e.to_string())]))?;
    Ok(json!({ "picked": true, "path": path.to_string_lossy() }))
}

#[tauri::command]
pub async fn ds_set_node_path(app: AppHandle, path: String) -> Result<(), String> {
    let paths = Paths::detect();
    let mut s = settings();
    s.ds_node_path = Some(path.trim().to_string()).filter(|p| !p.is_empty());
    let r = save_settings(&paths, &s);
    let _ = app.emit("state-changed", ());
    r
}
