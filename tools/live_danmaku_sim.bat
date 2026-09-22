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

if not exist "%VENVPY%" (
    echo 模拟器环境还没装，正在安装（仅需一次）……
    where uv >nul 2>nul || (echo 需要先安装 uv: https://docs.astral.sh/uv/ & exit /b 1)
    uv venv %VENV% --python 3.12 || exit /b 1
    uv pip install --python %VENVPY% mujoco onnxruntime numpy better-actuator-models glfw pyopengl || exit /b 1
)

"%VENVPY%" -c "import mss, win32gui, rapidocr_onnxruntime" >nul 2>nul
if errorlevel 1 (
    echo [启动] 安装弹幕桥依赖（mss/pywin32/rapidocr_onnxruntime）…
    uv pip install --python %VENVPY% mss pywin32 rapidocr_onnxruntime || exit /b 1
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
