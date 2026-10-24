@echo off
cd /d "%~dp0"
echo === Elsewhere PC ===
echo 1/2: tunneld inditasa (rendszergazda jogot fog kerni)...
powershell -NoProfile -Command "Start-Process cmd -Verb RunAs -ArgumentList '/k python -m pymobiledevice3 remote tunneld'"
echo Varok 8 masodpercet, hogy a tunneld felalljon...
timeout /t 8 /nobreak >nul
echo 2/2: program inditasa...
python elsewhere_pc.py
pause
