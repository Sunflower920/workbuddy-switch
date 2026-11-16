@echo off
setlocal
rem ============================================================
rem  One-click unify: clean soft-deleted/empty sessions, fill every
rem  session into all 3 accounts, AND remap session space_id to the
rem  owner account's own space (fixes sessions hidden in the UI).
rem  Pure ASCII on purpose (cmd reads .bat as GBK).
rem  Result log: C:\Users\WG-WYZ\.workbuddy-switch\unify-last.log
rem ============================================================
set "EXE=C:\Users\WG-WYZ\AppData\Local\SwitchSuite\sidecar\wbswitch\wbswitch.exe"
set "LOG=C:\Users\WG-WYZ\.workbuddy-switch\unify-last.log"

echo ============================================================
echo  UNIFY sessions across 3 accounts + fix space_id (hidden-session bug).
echo  Steps: quit WorkBuddy -^> clean + fill + space-fix -^> reopen WorkBuddy.
echo  A DB backup was already made before this (backups/pre-unify-*).
echo  The chat with the agent will be interrupted - this is normal.
echo  After WorkBuddy reopens, ask the agent to verify unify-last.log.
echo.
echo  Save all work in WorkBuddy before continuing.
echo ============================================================
echo.
pause

echo [%date% %time%] STEP 1: quit WorkBuddy > "%LOG%"
"%EXE%" kill --edition cn --json >> "%LOG%" 2>&1
echo [%date% %time%] STEP 2: unify (clean + fill) >> "%LOG%"
"%EXE%" unify --json >> "%LOG%" 2>&1
echo [%date% %time%] STEP 3: relaunch WorkBuddy >> "%LOG%"
"%EXE%" launch --edition cn --json >> "%LOG%" 2>&1
echo [%date% %time%] DONE >> "%LOG%"

echo.
echo ===== DONE. WorkBuddy relaunched. =====
echo Log: %LOG%
echo Reopen this chat and ask the agent to verify.
pause
