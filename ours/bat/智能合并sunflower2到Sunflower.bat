@echo off
rem smart_merge: content-aware merge of sunflower 2 into Sunflower (current login).
rem Step 1 copies only sessions whose content is strictly newer in the source.
rem Step 2 (engine exe, no safe-delete shim) dedupes same-root pairs: updated
rem copies win, stale originals go to the recoverable quarantine.
rem Prerequisite: WorkBuddy client fully quit (writes the client database).
echo ============================================================
echo  Smart merge: sunflower 2 into Sunflower (current account)
echo.
echo  Expect: 2 sessions copied, 25 skipped.
echo  Takes under a minute. DO NOT close this window.
echo  DO NOT reopen WorkBuddy until you see "DONE".
echo ============================================================
echo.
echo [1/2] Content-aware copy ...
"C:\Users\WG-WYZ\.workbuddy\binaries\python\versions\3.13.12\python.exe" "E:\ÍõÓÂÖÇ\WorkBuddy-Switch\ours\smart_merge.py" --source db3237c3-dbf6-47fd-b800-81f65b00c255 --no-dedupe
echo.
echo [2/2] Dedupe (updated copies win, stale originals quarantined) ...
"C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe" sessions --dedupe 21bd0bce-e13d-48e9-8f68-1e0c20b81168 --json
echo.
echo ===== DONE. You can reopen WorkBuddy now. Press any key to close. =====
pause >nul
