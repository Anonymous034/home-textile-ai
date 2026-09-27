@echo off
start "" /wait powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-ark-key-gui.ps1"
