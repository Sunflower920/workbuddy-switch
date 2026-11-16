# 我们的复刻版（fork）说明

## 基线

- 上游：https://github.com/Danjack85/workbuddy-switch （MIT）
- 本仓库：https://github.com/Sunflower920/workbuddy-switch （fork）
- 复刻基线：`main` @ 2026-10-12（dfea8c8，含 40 列 schema 支持与双版本隔离）

## 相对上游的全部改动

### 引擎补丁（2 处，共 8 行）

| 文件 | 改动 | 原因 |
|---|---|---|
| `wbswitch/paths.py` | `DEFAULT_EDITION = "intl"` → `"cn"` | 本机为国内版：数据根 `~/.workbuddy`、进程 `WorkBuddy.exe`。上游默认 intl 会落到不存在的 `~/.workbuddy-ai` |
| `wbswitch/profiles.py` | 旧档案 edition 兜底 `"intl"` → `"cn"` | 双版本改造前建的账号档案没有 edition 字段，按本机版本解析 |
| `wbswitch/sessions.py` | 会话写入改为按**实际列名**动态构造 INSERT（新增 `_session_insert_sql` / `_session_values`），移除按列数分派的 30/40 列写死字面量 | WorkBuddy 5.11.3 把 `sessions` 表从 40 列扩到 42 列（新增 `space_id` / `released_from_automation_id`），旧代码 `_match_sessions_schema` 列数不匹配直接 `return`，导致会话复制/补回**全部静默失效**（表现为"同步没效果"）。动态列名后客户端再扩列无需改工具；只用必需列（id/cwd/user_id/created_at/updated_at）齐全作安全底线 |

### 引擎新增（复刻版自有功能，已收编进引擎）

| 文件 | 用途 |
|---|---|
| `wbswitch/smartmerge.py` | 内容感知合并：仅当源会话正文更大、或同大小但标题变化时才复制进目标，复制后旧原版由 dedupe 送隔离区 |
| `wbswitch/unify.py` | 三账号会话整理（一次性运维）：按归一化标题分组，清除软删/无正文空壳/同账号内冗余副本，把每个会话补齐到所有账号。与 smart-merge 的"防回灌"判据分离，避免健康正文因"目标已有同源副本"而永远补不进只有软删/空壳的目标账号 |
| `wbswitch/cli.py` | `smart-merge` 子命令（`--source/--target/--no-dedupe/--dry-run/--json`，支持 `--envelope`）；`unify` 子命令（`--dry-run/--json`，清软删空壳并把会话补齐到所有账号） |
| `desktop/src-tauri/src/workbuddy.rs` | `wb_smart_merge` 命令（供界面调用） |
| `desktop/src/workbuddy.js` | 账号卡片「智能合并」按钮（dry-run → 确认框 → 执行） |

### 自有模块（`ours/`，与引擎解耦，升级引擎直接覆盖源码不影响这些文件）

| 模块 | 用途 |
|---|---|
| `ours/validate_copy.py` | copy dry-run 校验（强制 cn、绕过忙碌检查） |
| `ours/bat/` | 无 GUI 等价的备胎脚本（全量 sync、清理孤儿），见其 README |

## 上游同步

```bash
git fetch upstream
git merge upstream/main   # 我们的补丁只有 2 处，冲突好解
```

## 构建侧车

```bash
# venv：~/.workbuddy/binaries/python/envs/default（已装 PyInstaller）
~/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m PyInstaller build-sidecar.spec --noconfirm
# 产物 dist/wbswitch/ → 替换 AppData\Local\SwitchSuite\sidecar\wbswitch\
# 原引擎备份在 sidecar\wbswitch.bak-20261021\
```
