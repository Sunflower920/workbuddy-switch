@echo off
rem Copy sunflower 2's genuinely-new sessions into Sunflower (the current login).
rem The same-root defense auto-skips the 26 copies made earlier;
rem only sessions whose root is not already in Sunflower get copied.
rem Prerequisite: WorkBuddy client fully quit (this writes the client database).
echo ============================================================
echo  Copy new sessions: sunflower 2 to Sunflower (current account)
echo.
echo  Both accounts keep their own sessions afterwards.
echo  Takes a few seconds. DO NOT close this window.
echo  DO NOT reopen WorkBuddy until you see "DONE".
echo ============================================================
echo.
"C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe" sessions --copy db3237c3-dbf6-47fd-b800-81f65b00c255 --to 21bd0bce-e13d-48e9-8f68-1e0c20b81168 --json
echo.
echo ===== DONE. You can reopen WorkBuddy now. Press any key to close. =====
pause >nul
