@echo off
rem Windows: install everything for the lab equipment and the analysis.
rem Options: see equipment\packaging\windows\install.ps1
call "%~dp0equipment\packaging\windows\install.bat" %*
