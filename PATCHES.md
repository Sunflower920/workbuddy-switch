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

### 引擎新增（复刻版自有功能，已收编进引擎）

| 文件 | 用途 |
|---|---|
| `wbswitch/smartmerge.py` | 内容感知合并：仅当源会话正文更大、或同大小但标题变化时才复制进目标，复制后旧原版由 dedupe 送隔离区 |
| `wbswitch/cli.py` | `smart-merge` 子命令（`--source/--target/--no-dedupe/--dry-run/--json`，支持 `--envelope`） |
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
