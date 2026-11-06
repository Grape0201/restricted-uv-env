<#
.SYNOPSIS
制限環境内の Windows クライアント端末に uv 本体・uv.toml・アップデートコマンドをインストール／更新します。

.PARAMETER MirrorBaseUrl
制限環境内の Linux Web サーバー URL (例: "http://192.168.1.10")

.PARAMETER Force
既に同じバージョンの uv が入っていても強制的に再ダウンロード・上書きします。
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$MirrorBaseUrl = $env:UV_MIRROR_URL,

    [Parameter(Mandatory = $false)]
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($MirrorBaseUrl)) {
    Write-Host "[入力] 制限環境内の Linux ミラーサーバー URL を入力してください (例: http://192.168.1.10)" -ForegroundColor Yellow
    $MirrorBaseUrl = Read-Host "MirrorBaseUrl"
}
$MirrorBaseUrl = $MirrorBaseUrl.TrimEnd("/")

$InstallDir = Join-Path $env:USERPROFILE ".local\bin"
$ConfigDir = Join-Path $env:APPDATA "uv"
$ConfigFile = Join-Path $ConfigDir "uv.toml"

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " 制限環境向け uv セットアップ & アップデート (Windows)" -ForegroundColor Cyan
Write-Host " ミラーサーバー: $MirrorBaseUrl"
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. サーバー上の最新バージョン確認と uv.exe のダウンロード
$ServerVer = ""
try {
    $ServerVer = (Invoke-RestMethod -Uri "$MirrorBaseUrl/uv/version.txt" -TimeoutSec 15).Trim()
} catch {
    Write-Verbose "version.txt の取得をスキップしました: $_"
}

$UvExePath = Join-Path $InstallDir "uv.exe"
$CurrentVer = ""
if (Test-Path $UvExePath) {
    try {
        $VerLine = (& $UvExePath --version)
        $CurrentVer = ($VerLine -split "\s+")[1]
    } catch {}
}

if ((-not $Force) -and (-not [string]::IsNullOrWhiteSpace($ServerVer)) -and ($CurrentVer -eq $ServerVer)) {
    Write-Host "[1/3] uv は既に最新バージョン ($CurrentVer) です。" -ForegroundColor Green
} else {
    Write-Host "[1/3] uv バイナリ ($($ServerVer ? $ServerVer : 'latest')) をダウンロード・展開しています..."
    $TmpZip = Join-Path $env:TEMP "uv-win-x86_64-$([guid]::NewGuid().ToString('N')).zip"
    $TmpExtract = Join-Path $env:TEMP "uv-extract-$([guid]::NewGuid().ToString('N'))"
    try {
        Invoke-WebRequest -Uri "$MirrorBaseUrl/uv/latest/uv-x86_64-pc-windows-msvc.zip" -OutFile $TmpZip -UseBasicParsing
        Expand-Archive -Path $TmpZip -DestinationPath $TmpExtract -Force

        $FoundUv = Get-ChildItem -Path $TmpExtract -Filter "uv.exe" -Recurse | Select-Object -First 1
        $FoundUvx = Get-ChildItem -Path $TmpExtract -Filter "uvx.exe" -Recurse | Select-Object -First 1

        if ($null -eq $FoundUv) {
            throw "ダウンロードした ZIP 内に uv.exe が見つかりませんでした。"
        }

        # 実行中の uv.exe がある場合のロック回避のため、既存ファイルを一旦リネーム退避して上書き
        if (Test-Path $UvExePath) {
            $OldPath = "$UvExePath.old"
            Remove-Item $OldPath -Force -ErrorAction SilentlyContinue
            Rename-Item -Path $UvExePath -NewName "uv.exe.old" -Force -ErrorAction SilentlyContinue
        }

        Copy-Item -Path $FoundUv.FullName -Destination $UvExePath -Force
        if ($null -ne $FoundUvx) {
            Copy-Item -Path $FoundUvx.FullName -Destination (Join-Path $InstallDir "uvx.exe") -Force
        }
        Remove-Item "$UvExePath.old" -Force -ErrorAction SilentlyContinue

        $InstalledVer = (& $UvExePath --version)
        Write-Host "  -> インストール完了: $InstalledVer (配置先: $UvExePath)" -ForegroundColor Green
    } finally {
        Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 2. uv.toml の作成・更新
Write-Host "[2/3] uv 設定ファイル ($ConfigFile) を構成しています..."
$UvTomlContent = @"
# ==============================================================================
# 制限環境向け uv グローバル設定 (自動生成)
# ==============================================================================

# 内部ミラーサーバーから python-build-standalone を取得
python-install-mirror = "$MirrorBaseUrl/python"

# 内部ミラーサーバーのフラット Wheel 置き場をデフォルトインデックスとして使用（外部 PyPI への通信を無効化）
[[index]]
name = "internal-wheels"
url = "$MirrorBaseUrl/wheels/"
format = "flat"
default = true
"@
Set-Content -Path $ConfigFile -Value $UvTomlContent -Encoding UTF8
Write-Host "  -> $ConfigFile を更新しました"

# 3. いつでもコマンド一発でアップデートできる uv-offline-update を作成
Write-Host "[3/3] アップデート用コマンド ($InstallDir\uv-offline-update.cmd) を構成しています..."
$UpdatePs1Path = Join-Path $InstallDir "uv-offline-update.ps1"
$UpdateCmdPath = Join-Path $InstallDir "uv-offline-update.cmd"

# スクリプト自身を保存しておき、uv-offline-update でいつでも呼び出せるようにする
Copy-Item -Path $MyInvocation.MyCommand.Path -Destination $UpdatePs1Path -Force

$CmdContent = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$UpdatePs1Path" -MirrorBaseUrl "$MirrorBaseUrl" %*
"@
Set-Content -Path $UpdateCmdPath -Value $CmdContent -Encoding ASCII

# ユーザー環境変数 PATH への登録確認
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($null -eq $UserPath) -or ($UserPath -split ";" -notcontains $InstallDir)) {
    $NewUserPath = if ([string]::IsNullOrWhiteSpace($UserPath)) { $InstallDir } else { "$InstallDir;$UserPath" }
    [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
    $env:Path = "$InstallDir;$env:Path"
    Write-Host "  -> ユーザー環境変数 PATH に $InstallDir を追加しました" -ForegroundColor Green
}

Write-Host "`n[完了] セットアップが完了しました！" -ForegroundColor Green
Write-Host "  - Python のインストール : uv python install 3.12"
Write-Host "  - uv 本体のアップデート : uv-offline-update"
