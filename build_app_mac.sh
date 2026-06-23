#!/bin/bash
echo "===================================================================="
echo "Building Standalone macOS Application Bundle (.app) using PyInstaller"
echo "===================================================================="

# Ensure we are in the virtual environment
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Install PyInstaller if not already installed
if ! command -v pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Build macOS app bundle
echo "Running PyInstaller..."
pyinstaller --noconfirm --onefile --windowed \
            --name="Karnataka_Electoral_Roll_Extractor" \
            --add-data "electoral_roll_template.xlsx:." \
            --collect-data customtkinter \
            --exclude-module paddle \
            --exclude-module paddleocr \
            --exclude-module paddlepaddle \
            app.py

echo "===================================================================="
echo "Build completed! Standalone App bundle is located in: dist/Karnataka_Electoral_Roll_Extractor.app"
echo "===================================================================="
