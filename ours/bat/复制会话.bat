@echo off
rem Session copy: Sunflower to sunflower 2 (independent copies, both keep theirs).
rem Pure ASCII on purpose: cmd reads .bat files as GBK, any non-ASCII breaks it.
echo ============================================================
echo  Session copy: Sunflower to sunflower 2
echo.
echo  Takes about 1 minute. Progress is printed below.
echo  While this window is open:
echo    - DO NOT close this window
echo    - DO NOT reopen WorkBuddy
echo  Wait until you see "DONE" at the bottom.
echo ============================================================
echo.
"C:\Users\WG-WYZ\.workbuddy\binaries\python\versions\3.13.12\python.exe" "E:\王勇智\WorkBuddy-Switch\ours\bat\copy_sessions.py"
echo.
echo ===== DONE. You can reopen WorkBuddy now. Press any key to close. =====
pause >nul
