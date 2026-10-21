# -*- coding: utf-8 -*-
"""CI 出包后清理：退役被 GUI 覆盖的 .bat 驱动，同步更新仓库与桌面。"""
import shutil
import subprocess
from pathlib import Path

WS = Path(r"E:\王勇智\WorkBuddy-Switch")
DESK = Path(r"C:\Users\WG-WYZ\OneDrive\Desktop")

# 已被 SwitchSuite 界面覆盖的操作（复制/智能合并按钮），退役
retired = [
    "智能合并sunflower2到Sunflower.bat",
    "复制会话.bat",
    "复制sunflower2新会话到Sunflower.bat",
    "copy_sessions.py",
]
# 保留：clean_orphans.bat（无 GUI 等价）、合并sunflower2到Sunflower.bat（全量 sync 备胎）

for n in retired:
    for base in (DESK, WS / "ours" / "bat"):
        p = base / n
        if p.exists():
            p.unlink()
            print(f"已移除: {p}")

# ours/smart_merge.py：已被引擎 wbswitch/smartmerge.py 收编，移除免双份维护
p = WS / "ours" / "smart_merge.py"
if p.exists():
    p.unlink()
    print(f"已移除（被引擎收编）: {p}")

# ours/make_merge_bat.py：其产物（智能合并.bat）已退役
p = WS / "ours" / "make_merge_bat.py"
if p.exists():
    p.unlink()
    print(f"已移除（产物已退役）: {p}")

# ours/bat/README.md：更新保留清单
(WS / "ours" / "bat" / "README.md").write_text("""# 本机一键驱动（machine-specific，备胎）

SwitchSuite 界面已覆盖大部分操作，这里只留**没有 GUI 等价**的备胎。
内含本机绝对路径；内容为纯 ASCII 或 GBK 编码（cmd 按 GBK 读批处理）。
桌面上的副本才是运行入口；要改先改这里的，再复制到桌面。

| 文件 | 用途 | 前提 |
|---|---|---|
| `合并sunflower2到Sunflower.bat` | 全量 sync + dedupe（记忆/连接器/设置/会话整体并入；sunflower 2 会腾空）——GUI 无此入口 | 客户端完全退出 |
| `clean_orphans.bat` | 清理 2026-10-21 中断运行遗留的孤儿文件（GBK） | 无需退客户端 |

已退役（GUI 按钮覆盖）：复制会话、智能合并、反向复制及其驱动。
""", encoding="utf-8")

# PATCHES.md：更新自有模块清单
p = WS / "PATCHES.md"
s = p.read_text(encoding="utf-8")
s = s.replace(
    "### 自有模块（`ours/`，与引擎解耦，升级引擎直接覆盖源码不影响这些文件）\n\n"
    "| 模块 | 用途 |\n|---|---|\n"
    "| `ours/smart_merge.py` | 内容感知合并：补上游同根源防线盲区——仅当源会话正文更大、或同大小但标题变化时才复制进目标，复制后旧原版由 dedupe 送隔离区 |\n"
    "| `ours/validate_copy.py` | copy dry-run 校验（强制 cn、绕过忙碌检查） |\n"
    "| `ours/make_merge_bat.py` | 生成「智能合并」一键批处理（GBK 编码） |",
    "### 引擎新增（复刻版自有功能，已收编进引擎）\n\n"
    "| 文件 | 用途 |\n|---|---|\n"
    "| `wbswitch/smartmerge.py` | 内容感知合并：仅当源会话正文更大、或同大小但标题变化时才复制进目标，复制后旧原版由 dedupe 送隔离区 |\n"
    "| `wbswitch/cli.py` | `smart-merge` 子命令（`--source/--target/--no-dedupe/--dry-run/--json`，支持 `--envelope`） |\n"
    "| `desktop/src-tauri/src/workbuddy.rs` | `wb_smart_merge` 命令（供界面调用） |\n"
    "| `desktop/src/workbuddy.js` | 账号卡片「智能合并」按钮（dry-run → 确认框 → 执行） |\n\n"
    "### 自有模块（`ours/`，与引擎解耦，升级引擎直接覆盖源码不影响这些文件）\n\n"
    "| 模块 | 用途 |\n|---|---|\n"
    "| `ours/validate_copy.py` | copy dry-run 校验（强制 cn、绕过忙碌检查） |\n"
    "| `ours/bat/` | 无 GUI 等价的备胎脚本（全量 sync、清理孤儿），见其 README |")
assert "wbswitch/smartmerge.py" in s, "PATCHES.md 替换未命中"
p.write_text(s, encoding="utf-8")
print("PATCHES.md 已更新")

def git(*args):
    r = subprocess.run(["git", *args], cwd=WS, capture_output=True, text=True)
    if r.returncode != 0:
        print("git 失败:", r.stderr[:200])
        raise SystemExit(1)
    return r.stdout.strip()

git("add", "-A")
git("commit", "-q", "-m",
    "chore: smart-merge 已入引擎与界面，退役被 GUI 覆盖的 .bat 驱动\n\n"
    "- 移除 ours/smart_merge.py（由 wbswitch/smartmerge.py 收编）\n"
    "- 移除 ours/make_merge_bat.py 与 3 个被 GUI 按钮覆盖的 .bat + copy_sessions.py\n"
    "- ours/bat 仅留无 GUI 等价备胎（全量 sync、清理孤儿）")
git("push", "-q", "origin", "main")
print("已提交推送")
