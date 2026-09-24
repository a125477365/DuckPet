@echo off
rem 启动 DuckPet 自主鸭 3D 仿真（Windows 版）。
rem Windows 上 MuJoCo viewer 不需要 mjpython，直接 python 运行。
rem
rem   tools\sim_duckpet_3d.bat            # 3D 窗口 + 终端文字指令
rem   tools\sim_duckpet_3d.bat --headless # 无窗口自动验证
rem   tools\sim_duckpet_3d.bat --danmaku  # 同时嵌入直播伴侣弹幕监听线程
setlocal enabledelayedexpansion
rem 中文 cmd 默认 GBK：弹幕 emoji 会崩 print，统一切 UTF-8
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
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

"%VENVPY%" tools\sim_duckpet_3d.py %*
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
