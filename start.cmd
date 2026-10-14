@echo off
rem Double-click entry point; bypasses the default policy that blocks running .ps1 files.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
