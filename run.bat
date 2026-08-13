@echo off
chcp 65001 >nul
rem 生长词库 3.0 双击启动脚本：读取 config.json 跑完整管道（词表+审计；词云由 no_cloud 控制）。
rem 第一次使用：把 config.example.json 复制为 config.json，填好 input 语料路径再双击本脚本。
cd /d "%~dp0"
python -m grow3.cli --config config.json
echo.
pause
