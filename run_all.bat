@echo off
chcp 65001 >nul
rem 生长词库 3.0 一键双步：① 跑核心管道（词表+词云）② 标题索引补集并注入词云
rem 补集功能由 config.json 的 title_complement 开关控制（true=开/默认，false=关）。
rem 第一次使用：把 config.example.json 复制为 config.json，填好 input 语料路径再双击本脚本。
cd /d "%~dp0"
python -m grow3.cli --config config.json
echo.
rem 读 config.json 的 title_complement 开关（文件缺失或字段缺失时默认开）
python -c "import json,os,sys; on=json.load(open('config.json',encoding='utf-8')).get('title_complement',True) if os.path.exists('config.json') else True; sys.exit(0 if on else 1)"
if errorlevel 1 goto skip_comp
echo ============ 补集索引 ============
python -m grow3.title_index --config config.json
goto end
:skip_comp
echo.
echo [补集索引已关闭] config.json 的 title_complement=false，跳过补集功能。
:end
echo.
pause
