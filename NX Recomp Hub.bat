@echo off
rem Starts NX Recomp Hub with the project's own Python environment (everything stays in this folder).
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0nxrecomp\nxrecomp.py"
