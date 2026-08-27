@echo off
rem Double-click launcher for the SBConnect Windows Receiver.
cd /d "%~dp0"
python -m sbconnect_receiver %*
