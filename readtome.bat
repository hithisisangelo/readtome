@echo off
rem Drag a .pdf or .epub onto this file to turn it into an audiobook.
rem Extra options can follow, e.g.:  readtome.bat book.epub --speed 1.2
if "%~1"=="" (
  "%~dp0.venv\Scripts\readtome.exe" --help
) else (
  "%~dp0.venv\Scripts\readtome.exe" %* -o "%~dp0audiobooks"
)
pause
