@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Instalace aplikace Hulmani (Windows + NVIDIA GPU) ===
where py >nul 2>nul || (echo Nenasel jsem Python. Nainstalujte Python 3.11 nebo 3.12 z python.org a zaskrtnete "Add to PATH". & pause & exit /b 1)
if not exist .venv py -3 -m venv .venv || (echo Nepodarilo se vytvorit virtualni prostredi. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo --- PyTorch s podporou CUDA pro RTX 3060 ---
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 || (echo Instalace PyTorch selhala. & pause & exit /b 1)
pip install -r requirements.txt || (echo Instalace knihoven selhala. & pause & exit /b 1)
python -c "import torch; print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NENALEZENA - pobezi to na CPU (pomaleji)')"
echo.
echo Hotovo. Aplikaci spustite souborem start_windows.bat
pause
