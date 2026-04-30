@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-bridge.ps1" %*

