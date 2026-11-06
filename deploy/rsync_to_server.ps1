<#
.SYNOPSIS
Box フォルダ内の mirror_data を制限環境内の Linux Web サーバーへ rsync で差分同期します。

.DESCRIPTION
Windows 上にインストールされた rsync.exe (Git for Windows / cwRsync / Scoop 等)
または WSL 内の rsync を自動検出し、Windows パスを自動変換して転送します。

.PARAMETER RemoteTarget
転送先の SSH ターゲットとパス (例: "user@192.168.1.10:/var/www/uv-mirror")

.PARAMETER SourceDir
Box 内の mirror_data パス (デフォルト: スクリプトの親フォルダにある mirror_data)

.PARAMETER DeleteRemoved
指定すると --delete オプションを付与し、Box 側で削除したファイルをサーバー側からも削除します。
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$RemoteTarget = $env:UV_MIRROR_REMOTE,

    [Parameter(Mandatory = $false)]
    [string]$SourceDir = (Join-Path $PSScriptRoot "..\mirror_data"),

    [Parameter(Mandatory = $false)]
    [switch]$DeleteRemoved
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RemoteTarget)) {
    Write-Host "[入力] 転送先の Linux サーバーを指定してください (例: user@192.168.1.10:/var/www/uv-mirror)" -ForegroundColor Yellow
    $RemoteTarget = Read-Host "RemoteTarget"
}

$ResolvedSource = (Resolve-Path $SourceDir).Path
if (-not (Test-Path $ResolvedSource -PathType Container)) {
    throw "同期元フォルダが見つかりません: $SourceDir"
}

$RsyncArgs = @(
    "-rtvz",
    "--partial",
    "--progress",
    "--chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r",
    "--exclude=.bin/",
    "--exclude=*.part"
)
if ($DeleteRemoved) {
    $RsyncArgs += "--delete"
}

# 1. ネイティブの rsync.exe (Git Bash / cwRsync 等) があるか確認
$RsyncCmd = Get-Command rsync.exe -ErrorAction SilentlyContinue
if ($null -ne $RsyncCmd) {
    # C:\Users\foo\mirror_data -> /c/Users/foo/mirror_data/ (MSYS/cwRsync 互換パス)
    $Drive = $ResolvedSource.Substring(0, 1).ToLower()
    $Rest = $ResolvedSource.Substring(2).Replace("\", "/").TrimEnd("/")
    # cwRsync は /cygdrive/c/、Git/MSYS2 は /c/ を解釈するが、rsync.exe の出力で自動判別
    $VerOut = (& rsync.exe --version 2>&1 | Out-String)
    if ($VerOut -match "cygpath|cygwin") {
        $UnixSource = "/cygdrive/$Drive$Rest/"
    } else {
        $UnixSource = "/$Drive$Rest/"
    }

    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " rsync.exe で Linux Web サーバーへ差分同期します" -ForegroundColor Cyan
    Write-Host " 同期元 : $UnixSource"
    Write-Host " 同期先 : $RemoteTarget/"
    Write-Host "==================================================================" -ForegroundColor Cyan

    & rsync.exe @RsyncArgs $UnixSource "$($RemoteTarget.TrimEnd('/'))/"
    if ($LASTEXITCODE -ne 0) {
        throw "rsync がエラー終了しました (ExitCode: $LASTEXITCODE)"
    }
}
elseif ($null -ne (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    # 2. WSL 経由の rsync を使用
    $UnixSource = (& wsl.exe wslpath -u ($ResolvedSource.Replace("\", "/"))).Trim() + "/"

    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " WSL rsync で Linux Web サーバーへ差分同期します" -ForegroundColor Cyan
    Write-Host " 同期元 : $UnixSource"
    Write-Host " 同期先 : $RemoteTarget/"
    Write-Host "==================================================================" -ForegroundColor Cyan

    & wsl.exe rsync @RsyncArgs $UnixSource "$($RemoteTarget.TrimEnd('/'))/"
    if ($LASTEXITCODE -ne 0) {
        throw "WSL rsync がエラー終了しました (ExitCode: $LASTEXITCODE)"
    }
}
else {
    throw "rsync.exe または WSL が見つかりません。Git for Windows / cwRsync / WSL のいずれかを導入してください。"
}

Write-Host "`n[完了] Linux Web サーバーへの rsync 同期が完了しました！" -ForegroundColor Green
