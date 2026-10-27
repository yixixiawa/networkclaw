@echo off
rem Launch NetworkClaw desktop GUI from a task-scheduler context (no console window).
cd /d D:\anyworkspace\python\Flower_engine
".venv\Scripts\python.exe" launcher.py --gui
