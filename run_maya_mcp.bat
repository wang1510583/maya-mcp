@echo off
cd /d "%~dp0"
"%~dp0.venv-mcp\Scripts\python.exe" -m maya_mcp.server
