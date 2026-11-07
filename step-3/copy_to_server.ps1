<#
.SYNOPSIS
Box 内の mirror_data を制限環境内の Linux Web サーバーへ xcopy で差分転送します。

.DESCRIPTION
Windows 標準の xcopy コマンドを利用して、Samba 等で共有された Linux サーバーのディレクトリへ
新しいファイル・更新されたファイルのみを安全に差分コピーします。追加ツール（rsync.exe 等）の導入は不要です。

.PARAMETER Destination
転送先のネットワーク共有パス (UNC) またはドライブ文字 (例: "\\192.168.1.10\uv-mirror" または "Z:\")

.PARAMETER SourceDir
Box 内の mirror_data パス (デフォルト: スクリプトの親フォルダにある mirror_data)
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$Destination = $env:UV_MIRROR_DEST,

    [Parameter(Mandatory = $false)]
    [string]$SourceDir = (Join-Path $PSScriptRoot "..\mirror_data")
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Destination)) {
    Write-Host "[入力] 転送先のネットワーク共有パス (UNC) またはドライブ文字を入力してください" -ForegroundColor Yellow
    Write-Host "例: \\192.168.1.10\uv-mirror または Z:\" -ForegroundColor Gray
    $Destination = Read-Host "Destination"
}

if ([string]::IsNullOrWhiteSpace($Destination)) {
    throw "転送先パスが指定されていません。"
}

$ResolvedSource = (Resolve-Path $SourceDir -ErrorAction SilentlyContinue)
if (-not $ResolvedSource -or -not (Test-Path $ResolvedSource.Path -PathType Container)) {
    throw "同期元フォルダが見つかりません: $SourceDir (先に step-1 で資材収集を実行してください)"
}
$SourcePath = $ResolvedSource.Path

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " xcopy で Linux Web サーバーへ差分転送します" -ForegroundColor Cyan
Write-Host " 同期元 : $SourcePath"
Write-Host " 同期先 : $Destination"
Write-Host "==================================================================" -ForegroundColor Cyan

# xcopy 引数:
# /E : サブディレクトリを含めてすべてコピー
# /I : コピー先が存在しない場合はディレクトリとみなす
# /Y : 上書き確認プロンプトを抑制
# /D : コピー元の日時が新しいファイルのみコピー（差分）
# /C : エラーが発生しても続行
# /H : 隠しファイルもコピー
# /R : 読み取り専用ファイルも上書き
$SourcePattern = Join-Path $SourcePath "*"
$DestPattern = $Destination.TrimEnd("\") + "\"

& xcopy.exe $SourcePattern $DestPattern /E /I /Y /D /C /H /R

$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 0) {
    Write-Host "`n[SUCCESS] Linux Web サーバーへの xcopy 転送が完了しました！" -ForegroundColor Green
} elseif ($ExitCode -eq 1) {
    Write-Host "`n[SUCCESS] 新しい差分ファイルはありませんでした（全て最新です）。" -ForegroundColor Green
} elseif ($ExitCode -eq 2) {
    Write-Host "`n[CANCEL] 中断されました。" -ForegroundColor Yellow
} else {
    throw "xcopy がエラー終了しました (ExitCode: $ExitCode)"
}
