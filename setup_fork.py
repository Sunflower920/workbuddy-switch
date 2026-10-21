# -*- coding: utf-8 -*-
"""一次性迁移：工作区重排为 fork 仓库布局，应用 cn 补丁，放入自有模块。"""
import shutil
import subprocess
import sys
from pathlib import Path

WS = Path(r"E:\王勇智\WorkBuddy-Switch")
REPO = WS / "workbuddy-switch"

assert (REPO / "wbswitch").is_dir(), "clone 不在预期位置"
assert (REPO / ".git").is_dir(), "clone 缺少 .git"

# ---- 1. 重排：clone 内容提到工作区根 ----
if (WS / "engine").is_dir():
    bak = WS / "engine.old-20261022"
    if bak.exists():
        shutil.rmtree(bak)
    shutil.move(str(WS / "engine"), str(bak))
mem, mem_tmp = WS / ".workbuddy", WS / ".workbuddy.tmp-migrate"
if mem.exists():
    shutil.move(str(mem), str(mem_tmp))
for item in list(REPO.iterdir()):
    shutil.move(str(item), str(WS / item.name))
REPO.rmdir()
if mem_tmp.exists():
    shutil.move(str(mem_tmp), str(WS / ".workbuddy"))
print("[1/6] 工作区已重排为仓库根")

# ---- 2. 补丁：paths.py DEFAULT_EDITION ----
p = WS / "wbswitch" / "paths.py"
s = p.read_text(encoding="utf-8")
old = ('#: 没有版本上下文时的默认版本。工具的历史数据都来自国际版数据根，\n'
       '#  保持"默认=国际版"，让所有旧调用点在改造期行为不变。\n'
       'DEFAULT_EDITION = "intl"')
new = ('#: 没有版本上下文时的默认版本。本机为国内版（数据根 ~/.workbuddy，\n'
       '#  进程 WorkBuddy.exe），默认按 cn 解析，避免落到不存在的 ~/.workbuddy-ai。\n'
       'DEFAULT_EDITION = "cn"')
assert old in s, "paths.py 补丁点未找到（上游变了？）"
p.write_text(s.replace(old, new), encoding="utf-8")

# ---- 3. 补丁：profiles.py 旧档案 edition 兜底 ----
p = WS / "wbswitch" / "profiles.py"
s = p.read_text(encoding="utf-8")
old = 'edition=paths.normalize_edition(str(d.get("edition") or "")) or "intl",'
new = 'edition=paths.normalize_edition(str(d.get("edition") or "")) or "cn",'
assert old in s, "profiles.py 补丁点未找到（上游变了？）"
p.write_text(s.replace(old, new), encoding="utf-8")
print("[2/6] cn 补丁已应用（2 处）")

# ---- 4. ours/ 自有模块（位置无关，升级引擎不受影响）----
ours = WS / "ours"
ours.mkdir(exist_ok=True)

sm = (WS / "smart_merge.py").read_text(encoding="utf-8")
sm = sm.replace(
    'ENGINE_DIR = Path(__file__).resolve().parent / "engine"',
    'ENGINE_DIR = Path(__file__).resolve().parents[1]  # 仓库根（wbswitch/ 所在）')
assert "parents[1]" in sm, "smart_merge ENGINE_DIR 替换失败"
(ours / "smart_merge.py").write_text(sm, encoding="utf-8")

vc = (WS / "validate_copy.py").read_text(encoding="utf-8")
vc = vc.replace(
    'sys.path.insert(0, r"E:\\王勇智\\WorkBuddy-Switch\\engine")',
    'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))')
assert "parents[1]" in vc, "validate_copy 路径替换失败"
if "from pathlib import Path" not in vc:
    vc = vc.replace("import sys, json", "import sys, json\nfrom pathlib import Path", 1)
(ours / "validate_copy.py").write_text(vc, encoding="utf-8")

mb = (WS / "make_merge_bat.py").read_text(encoding="utf-8")
mb = mb.replace(r"E:\王勇智\WorkBuddy-Switch\smart_merge.py",
                r"E:\王勇智\WorkBuddy-Switch\ours\smart_merge.py")
(ours / "make_merge_bat.py").write_text(mb, encoding="utf-8")
print("[3/6] ours/ 自有模块已就位（3 个）")

# ---- 5. PATCHES.md（仓库根）----
(WS / "PATCHES.md").write_text("""# 我们的复刻版（fork）说明

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
# 产物 dist/wbswitch/ → 替换 AppData\\Local\\SwitchSuite\\sidecar\\wbswitch\\
# 原引擎备份在 sidecar\\wbswitch.bak-20261021\\
```
""", encoding="utf-8")

# ---- 6. .gitignore ----
gi = WS / ".gitignore"
existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
extra = "\n".join([".workbuddy/", "__pycache__/", "*.pyc", "dist/", "build/",
                   "engine.old-*/"]) + "\n"
if ".workbuddy/" not in existing:
    gi.write_text(existing + extra, encoding="utf-8")

for fn in ("smart_merge.py", "validate_copy.py", "make_merge_bat.py"):
    f = WS / fn
    if f.exists():
        f.unlink()
print("[4-6/6] PATCHES.md / .gitignore / 清理完成")

# ---- 7. git 提交 ----
def git(*args):
    r = subprocess.run(["git", *args], cwd=WS, capture_output=True, text=True)
    if r.returncode != 0:
        print("git 失败:", " ".join(args), r.stderr[:300])
        sys.exit(1)
    return r.stdout.strip()

name = git("config", "user.name") or "Sunflower920"
if not git("config", "user.name"):
    git("config", "user.name", "Sunflower920")
    git("config", "user.email", "Sunflower920@users.noreply.github.com")
git("add", "-A")
git("commit", "-m",
    "复刻基线：上游 main @ 2026-10-12 + 国内版(cn)补丁 + 自有模块 smart_merge\n\n"
    "- paths.py/profiles.py: 默认版本 intl -> cn（本机为国内版）\n"
    "- ours/smart_merge.py: 内容感知合并（补同根源防线盲区）\n"
    "- ours/validate_copy.py, ours/make_merge_bat.py\n"
    "- PATCHES.md: 复刻说明与上游同步方法")
print("[git] 提交完成:", git("log", "--oneline", "-1")[:80])
