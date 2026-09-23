@echo off
rem 直播模式一键启动（Windows）：3D 物理仿真鸭 + 直播伴侣评论区弹幕桥（内嵌线程）。
rem
rem   tools\live_danmaku_sim.bat                # 只转发像指令的弹幕
rem   tools\live_danmaku_sim.bat --all          # 转发所有弹幕
rem   tools\live_danmaku_sim.bat --region 0.66,0.30,0.32,0.45
rem
rem 弹幕桥是仿真内线程（--danmaku）：评论区弹幕和终端键盘输入同时生效。
rem 注意：Windows 截图按屏幕区域抓取，直播伴侣窗口请勿最小化/遮挡。
rem 退出：Ctrl+C。
setlocal enabledelayedexpansion
cd /d "%~dp0\.."
set VENV=third_party\microduck_rl\.venv-sim
set VENVPY=%VENV%\Scripts\python.exe

rem 依赖安装器：优先 uv（快、会自动装 Python 3.12）；
rem 没有 uv 就回退系统 Python 自带的 venv+pip（要求 3.10+，3.12 最稳）
set HAVE_UV=0
where uv >nul 2>nul && set HAVE_UV=1

if not exist "%VENVPY%" (
    echo 模拟器环境还没装，正在安装（仅需一次）……
    if "!HAVE_UV!"=="1" (
        uv venv %VENV% --python 3.12 || exit /b 1
        uv pip install --python %VENVPY% mujoco onnxruntime numpy better-actuator-models glfw pyopengl || exit /b 1
    ) else (
        echo [提示] 没找到 uv，回退到系统 Python（winget install astral-sh.uv 可装 uv，更快）
        call :find_python || exit /b 1
        !PY! -m venv %VENV% || exit /b 1
        "%VENVPY%" -m pip install --upgrade pip || exit /b 1
        "%VENVPY%" -m pip install mujoco onnxruntime numpy better-actuator-models glfw pyopengl || exit /b 1
    )
)

"%VENVPY%" -c "import mss, win32gui, rapidocr_onnxruntime" >nul 2>nul
if errorlevel 1 (
    echo [启动] 安装弹幕桥依赖（mss/pywin32/rapidocr_onnxruntime）…
    if "!HAVE_UV!"=="1" (
        uv pip install --python %VENVPY% mss pywin32 rapidocr_onnxruntime || exit /b 1
    ) else (
        "%VENVPY%" -m pip install mss pywin32 rapidocr_onnxruntime || exit /b 1
    )
)

tasklist /fi "imagename eq webcastmate.exe" 2>nul | find /i "webcastmate" >nul
if errorlevel 1 (
    echo [启动] 没检测到直播伴侣进程，请先手动打开（弹幕桥会每 5 秒重试找窗口）
)

rem 旧参数翻译成 --danmaku-* 传给仿真
set ARGS=--danmaku
:argloop
if "%~1"=="" goto argdone
if /i "%~1"=="--all" (
    set ARGS=!ARGS! --danmaku-all
) else if /i "%~1"=="--region" (
    set ARGS=!ARGS! --danmaku-region %~2
    shift
) else if /i "%~1"=="--app" (
    set ARGS=!ARGS! --danmaku-app %~2
    shift
) else if /i "%~1"=="--interval" (
    set ARGS=!ARGS! --danmaku-interval %~2
    shift
) else (
    set ARGS=!ARGS! %~1
)
shift
goto argloop
:argdone

echo [启动] 3D 仿真 + 弹幕桥线程
"%VENVPY%" tools\sim_duckpet_3d.py !ARGS!
exit /b %errorlevel%

rem ---- 找一个 ^>=3.10 的系统 Python：先 py 启动器，再 PATH 里的 python ----
:find_python
set PY=
where py >nul 2>nul && (py -3.12 -c "pass" >nul 2>nul && set PY=py -3.12)
if not defined PY where py >nul 2>nul && (py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul && set PY=py -3)
if not defined PY (python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul && set PY=python)
if not defined PY (
    echo [错误] 没找到 ^>=3.10 的 Python。请装 uv（https://docs.astral.sh/uv/）或 Python 3.12（https://www.python.org/downloads/）
    exit /b 1
)
echo [提示] 使用 !PY!
exit /b 0
