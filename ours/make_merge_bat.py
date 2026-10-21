# -*- coding: utf-8 -*-
"""生成「智能合并」批处理（GBK 编码，含中文路径）并部署到桌面。"""
import shutil

PY = r"C:\Users\WG-WYZ\.workbuddy\binaries\python\versions\3.13.12\python.exe"
SM = r"E:\王勇智\WorkBuddy-Switch\ours\smart_merge.py"
EXE = r"C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe"
SRC = "db3237c3-dbf6-47fd-b800-81f65b00c255"
TGT = "21bd0bce-e13d-48e9-8f68-1e0c20b81168"

lines = [
    "@echo off",
    "rem smart_merge: content-aware merge of sunflower 2 into Sunflower (current login).",
    "rem Step 1 copies only sessions whose content is strictly newer in the source.",
    "rem Step 2 (engine exe, no safe-delete shim) dedupes same-root pairs: updated",
    "rem copies win, stale originals go to the recoverable quarantine.",
    "rem Prerequisite: WorkBuddy client fully quit (writes the client database).",
    "echo ============================================================",
    "echo  Smart merge: sunflower 2 into Sunflower (current account)",
    "echo.",
    "echo  Expect: 2 sessions copied, 25 skipped.",
    "echo  Takes under a minute. DO NOT close this window.",
    "echo  DO NOT reopen WorkBuddy until you see \"DONE\".",
    "echo ============================================================",
    "echo.",
    "echo [1/2] Content-aware copy ...",
    f'"{PY}" "{SM}" --source {SRC} --no-dedupe',
    "echo.",
    "echo [2/2] Dedupe (updated copies win, stale originals quarantined) ...",
    f'"{EXE}" sessions --dedupe {TGT} --json',
    "echo.",
    "echo ===== DONE. You can reopen WorkBuddy now. Press any key to close. =====",
    "pause >nul",
]

out = r"C:\Users\WG-WYZ\wbswitch-engine\智能合并sunflower2到Sunflower.bat"
with open(out, "w", encoding="gbk", errors="strict") as f:
    f.write("\n".join(lines) + "\n")
shutil.copy(out, r"C:\Users\WG-WYZ\OneDrive\Desktop\智能合并sunflower2到Sunflower.bat")
print("已生成并部署到桌面")

raw = open(out, "rb").read().decode("gbk")
assert "smart_merge.py" in raw and "--dedupe" in raw
print("GBK 编码校验通过")
