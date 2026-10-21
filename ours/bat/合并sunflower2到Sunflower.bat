@echo off
rem Merge sunflower 2 into Sunflower (the current login account).
rem   step 1: sync  - transfer sunflower 2's sessions (ownership) into Sunflower
rem   step 2: dedupe - collapse same-root pairs, keeping the largest/newest body
rem            (your updated sessions win; stale originals go to the recoverable trash)
rem Side effect: sunflower 2 is left with no sessions afterwards - all content
rem               lives in Sunflower, nothing is lost. Refill later with one copy.
rem Prerequisite: WorkBuddy client fully quit (both steps write the client database).
echo ============================================================
echo  Merge sunflower 2 into Sunflower (current account)
echo.
echo  Takes a few seconds. DO NOT close this window.
echo  DO NOT reopen WorkBuddy until you see "DONE".
echo ============================================================
echo.
echo [1/2] Syncing sunflower 2 into Sunflower ...
"C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe" sync --id 5bed03ff-62ca-4703-a783-4cf3aa22abfd --json
echo.
echo [2/2] Deduping same-root duplicates (keeps your updated sessions) ...
"C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe" sessions --dedupe 21bd0bce-e13d-48e9-8f68-1e0c20b81168 --json
echo.
echo ===== DONE. You can reopen WorkBuddy now. Press any key to close. =====
pause >nul
