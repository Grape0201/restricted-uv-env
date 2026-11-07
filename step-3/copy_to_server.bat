@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==================================================================
echo  Linux Web サーバーへの資材転送 (xcopy 差分同期)
echo ==================================================================

REM 1. コピー元フォルダの決定（デフォルト: プロジェクト直下の mirror_data）
set "SOURCE_DIR=%~dp0..\mirror_data"
if not "%UV_MIRROR_SOURCE%"=="" (
    set "SOURCE_DIR=%UV_MIRROR_SOURCE%"
)

if not exist "%SOURCE_DIR%" (
    echo [ERROR] 同期元フォルダが見つかりません: %SOURCE_DIR%
    echo 先に step-1 で資材収集 (run_sync.bat) を実行してください。
    echo.
    pause
    exit /b 1
)

REM 2. コピー先（Linux サーバーの共有フォルダ UNC パスまたはネットワークドライブ）の決定
set "DEST_DIR=%~1"
if "%DEST_DIR%"=="" (
    if not "%UV_MIRROR_DEST%"=="" (
        set "DEST_DIR=%UV_MIRROR_DEST%"
    )
)

if "%DEST_DIR%"=="" (
    echo [入力] 転送先のネットワーク共有パス (UNC) またはドライブ文字を入力してください。
    echo 例: \\192.168.1.10\uv-mirror または Z:\
    set /p "DEST_DIR=転送先パス: "
)

if "%DEST_DIR%"=="" (
    echo [ERROR] 転送先パスが指定されていません。
    echo 使い方: %~nx0 [転送先パス]
    echo.
    pause
    exit /b 1
)

REM パス末尾の余計な引用符を除去
set "DEST_DIR=%DEST_DIR:"=%"

echo.
echo 同期元 : "%SOURCE_DIR%"
echo 同期先 : "%DEST_DIR%"
echo.
echo xcopy コマンドで差分ファイルのみ転送します...
echo ------------------------------------------------------------------

REM xcopy オプション:
REM   /E : サブディレクトリ（空含む）をすべてコピー
REM   /I : コピー先が存在しない場合はディレクトリとして作成
REM   /Y : 既存ファイルを上書き確認なしでコピー
REM   /D : コピー元の日時が新しいファイルのみコピー（差分更新）
REM   /C : エラーが発生しても処理を続行
REM   /H : 隠しファイルも対象
REM   /R : 読み取り専用ファイルも上書き
xcopy "%SOURCE_DIR%\*" "%DEST_DIR%\" /E /I /Y /D /C /H /R

set "XCOPY_EXIT=%ERRORLEVEL%"
echo ------------------------------------------------------------------

if %XCOPY_EXIT% equ 0 (
    echo [SUCCESS] Linux Web サーバーへの資材転送が正常に完了しました！
) else if %XCOPY_EXIT% equ 1 (
    echo [SUCCESS] コピー対象の新しいファイルはありませんでした（全て最新状態です）。
) else if %XCOPY_EXIT% equ 2 (
    echo [CANCEL] ユーザーによって処理が中断されました。
) else (
    echo [ERROR] xcopy がエラーコード %XCOPY_EXIT% で終了しました。
    echo ネットワーク接続、共有フォルダへのアクセス権限、容量等を確認してください。
)

echo.
pause
exit /b %XCOPY_EXIT%
