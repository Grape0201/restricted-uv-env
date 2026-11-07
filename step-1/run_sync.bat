@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

REM Zscaler 等の OS 証明書ストアを uv で常に有効化
set UV_SYSTEM_CERTS=true

echo ==================================================================
echo  Box 向け uv オフラインミラー同期を開始します...
echo ==================================================================

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [INFO] uv run で sync_to_box.py を実行します
    uv run --system-certs sync_to_box.py -c config.toml
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo [INFO] python で sync_to_box.py を実行します
        python sync_to_box.py -c config.toml
    ) else (
        echo [ERROR] uv または python が見つかりません。
        echo 初回のみ powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 等で uv を導入してください。
        pause
        exit /b 1
    )
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] 同期中にエラーが発生しました。上記のログを確認してください。
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [SUCCESS] Box フォルダへの同期が完了しました！
pause
