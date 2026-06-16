@echo off
echo ====================================================================
echo Building Standalone Windows Executable using PyInstaller
echo ====================================================================

:: Install requirements
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt

:: Build standalone executable
echo Running PyInstaller...
pyinstaller --onefile --windowed --name="Karnataka_Electoral_Roll_Extractor" --add-data "electoral_roll_template.xlsx;." --collect-data customtkinter app.py

echo ====================================================================
echo Build completed! Executable is located in the "dist" directory.
echo ====================================================================
pause
