@echo off
rem Windowed test run of the native Pikmin 4 port. Everything stays under this folder (no C: drive use).
rem The log goes to ports\pikmin4\run\visual.log - close the window to stop.
setlocal
set "ROOT=%~dp0"
set "W=%ROOT%work\0100B7C00933A000"
set "TEMP=%ROOT%.cache\tmp"
set "TMP=%ROOT%.cache\tmp"
set "TOTK_SHADER_CAPTURE=%W%\shaders"
set "TOTK_SHADER_DIR=%W%\shaders\ryujinx"
set "TOTK_PROFILE_DIR=%ROOT%ports\pikmin4\run\saves"
set "TOTK_ROMFS=%W%\extract\RomFS"
cd /d "%ROOT%ports\pikmin4"
echo Starting Pikmin 4 (native)... log: %CD%\run\visual.log
UltraTears.exe "%W%\extract\ExeFS" > run\visual.log 2>&1
echo Exited with code %ERRORLEVEL%.
echo Translating shaders the game used for the first time (next run draws them)...
set "PYTHONPYCACHEPREFIX=%ROOT%.cache\pycache"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%nxrecomp\shaders_from_capture.py" "%W%\shaders"
pause
