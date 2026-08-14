@echo off
REM Global installer for win-harness (Windows)
REM Usage: install.bat [git-repo-url]
REM
REM After installation, the `win-harness` command is available globally.

setlocal

set "REPO_URL=%~1"
if "%REPO_URL%"=="" set "REPO_URL=https://github.com/fir3storm/win-harness.git"
set "INSTALL_DIR=%USERPROFILE%\.win-harness"

echo [1/4] Cloning win-harness...
if exist "%INSTALL_DIR%" (
    echo    Already installed at %INSTALL_DIR%, updating...
    cd /d "%INSTALL_DIR%"
    git pull --quiet
) else (
    git clone --depth 1 %REPO_URL% "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

echo [2/4] Installing Python package...
pip install -e . --quiet

echo [3/4] Verifying installation...
where win-harness >nul 2>&1
if errorlevel 1 (
    echo [ERROR] win-harness command not found after install.
    echo   Try: pip install -e . --user
    exit /b 1
)

echo [4/4] Installation complete!
echo.
echo   win-harness is now available globally.
echo   Run: win-harness list
echo   Or: win-harness plan "Your security task here"

endlocal
