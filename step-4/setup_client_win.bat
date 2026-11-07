@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ==================================================================
echo  制限環境向け uv クライアント環境セットアップ (Windows)
echo ==================================================================

set "MIRROR_URL=%~1"
if "%MIRROR_URL%"=="" (
    if not "%UV_MIRROR_URL%"=="" (
        set "MIRROR_URL=%UV_MIRROR_URL%"
    )
)

if "%MIRROR_URL%"=="" (
    echo [入力] 制限環境内の Linux Web サーバー URL を入力してください。
    echo 例: http://192.168.1.10
    set /p "MIRROR_URL=サーバーURL: "
)

if "%MIRROR_URL%"=="" (
    echo [ERROR] サーバーURLが指定されていません。
    echo.
    pause
    exit /b 1
)

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_client_win.ps1" -MirrorBaseUrl "%MIRROR_URL%"

set "PS_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %PS_EXIT%
