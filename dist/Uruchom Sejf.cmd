@echo off
rem Uruchamia Sejf w osobnym oknie przegladarki Edge, jak zwykly program.
rem Plik Sejf.html musi lezec w tym samym folderze co ten plik.
set "P=%~dp0Sejf.html"
set "P=%P:\=/%"
setlocal EnableDelayedExpansion
set "P=!P: =%%20!"
start "" msedge --app="file:///!P!"
