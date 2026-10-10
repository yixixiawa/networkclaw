@echo off
rem 批量陪跑的「计划任务」启动器。
rem
rem 为什么要用计划任务：本机环境会把游离的 python.exe 回收掉——2026-10-01 实测，
rem 即便用了 DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB（见 tools/spawn.py），
rem 启动后 4 分钟左右 python.exe 仍会消失（连带 llama-server 的包装进程一起），
rem 而 **llama-server.exe 这个子进程却活着**。说明回收是按进程名/imaege 来的，
rem 与 Job Object 无关（issues P24）。计划任务由 Task Scheduler 宿主拉起，
rem 不属于被回收的那一类，实测可以长时间存活。
rem
rem 用法： schtasks /Run /TN "NetworkClawBatch"
rem       日志看 logs\batch_task_<日期>.txt

setlocal
cd /d D:\anyworkspace\python\Agent-Rag-MCP-startup
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set FASTMCP_LOG_LEVEL=ERROR
".venv\Scripts\python.exe" tools\lab_batch.py --from 02 --rounds 16 --restart-every 2 --wait 900 > logs\batch_task_20261001_c.txt 2>&1
echo exit=%errorlevel% >> logs\batch_task_20261001_c.txt
endlocal
