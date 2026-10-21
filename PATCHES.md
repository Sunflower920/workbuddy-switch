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

### 自有模块（`ours/`，与引擎解耦，升级引擎直接覆盖源码不影响这些文件）

| 模块 | 用途 |
|---|---|
| `ours/smart_merge.py` | 内容感知合并：补上游同根源防线盲区——仅当源会话正文更大、或同大小但标题变化时才复制进目标，复制后旧原版由 dedupe 送隔离区 |
| `ours/validate_copy.py` | copy dry-run 校验（强制 cn、绕过忙碌检查） |
| `ours/make_merge_bat.py` | 生成「智能合并」一键批处理（GBK 编码） |

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
