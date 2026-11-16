@echo off
setlocal
rem ============================================================
rem  One-click smart merge: sunflower 2 -- Sunflower (current login)
rem  Flow: quit WorkBuddy -> smart-merge -> relaunch WorkBuddy
rem  Result log: C:\Users\WG-WYZ\.workbuddy-switch\merge-last.log
rem  Content is pure ASCII on purpose (cmd reads .bat as GBK).
rem ============================================================
set "EXE=C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe"
set "SRC=db3237c3-dbf6-47fd-b800-81f65b00c255"
set "TGT=21bd0bce-e13d-48e9-8f68-1e0c20b81168"
set "LOG=C:\Users\WG-WYZ\.workbuddy-switch\merge-last.log"

echo ============================================================
echo  Smart merge: sunflower 2 ==^> Sunflower (current login)
echo.
echo  This will CLOSE WorkBuddy, merge sessions, then REOPEN it.
echo  The chat with the agent will be interrupted - this is normal.
echo  After WorkBuddy reopens, come back and ask the agent to verify.
echo.
echo  Save all other work in WorkBuddy before continuing.
echo ============================================================
echo.
pause

echo [%date% %time%] STEP 1: quit WorkBuddy > "%LOG%"
"%EXE%" kill --edition cn --json >> "%LOG%" 2>&1
echo [%date% %time%] STEP 2: smart-merge >> "%LOG%"
"%EXE%" smart-merge --source %SRC% --target %TGT% --json --envelope >> "%LOG%" 2>&1
echo [%date% %time%] STEP 3: relaunch WorkBuddy >> "%LOG%"
"%EXE%" launch --edition cn --json >> "%LOG%" 2>&1
echo [%date% %time%] DONE >> "%LOG%"

echo.
echo ===== DONE. WorkBuddy relaunched. =====
echo Log: %LOG%
echo Reopen this chat and ask the agent to verify the result.
pause
