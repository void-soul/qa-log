@echo off
REM CodeBuddy hook wrapper —— 把 hook stdin 转发给 agent_log_hook.py
REM 用作 ~/.codebuddy/settings.json 里 hooks 的 command（Git Bash 可执行 .cmd）。
REM 任何失败都以 0 退出，绝不阻塞 CodeBuddy 会话。

setlocal

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  REM 常见 uv / 系统安装位置兜底
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PY (
  if exist "%USERPROFILE%\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe" set "PY=%USERPROFILE%\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe"
)

if not defined PY (
  echo [agent_log_hook] python not found, skipping >&2
  exit /b 0
)

%PY% "%~dp0agent_log_hook.py" %*
exit /b 0
