@echo off
rem 启动 DuckPet 自主鸭 3D 仿真（Windows 版）。
rem Windows 上 MuJoCo viewer 不需要 mjpython，直接 python 运行。
rem
rem   tools\sim_duckpet_3d.bat            # 3D 窗口 + 终端文字指令
rem   tools\sim_duckpet_3d.bat --headless # 无窗口自动验证
rem   tools\sim_duckpet_3d.bat --danmaku  # 同时嵌入直播伴侣弹幕监听线程
cd /d "%~dp0\.."

set VENV=third_party\microduck_rl\.venv-sim
set VENVPY=%VENV%\Scripts\python.exe

if not exist "%VENVPY%" (
    echo 模拟器环境还没装，正在安装（仅需一次）……
    where uv >nul 2>nul || (echo 需要先安装 uv: https://docs.astral.sh/uv/ & exit /b 1)
    uv venv %VENV% --python 3.12 || exit /b 1
    uv pip install --python %VENVPY% mujoco onnxruntime numpy better-actuator-models glfw pyopengl || exit /b 1
)

"%VENVPY%" tools\sim_duckpet_3d.py %*
