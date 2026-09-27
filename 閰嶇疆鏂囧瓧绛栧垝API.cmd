@echo off
chcp 65001 >nul
start "" /wait powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-planning-api-gui.ps1"
