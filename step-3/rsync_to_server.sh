#!/usr/bin/env bash
# ==============================================================================
# rsync_to_server.sh
# 制限環境内の Windows PC (Git Bash / WSL / MSYS2) または Linux から、
# Box 同期フォルダ内の mirror_data を Linux Web サーバーへ rsync 差分転送します。
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SOURCE="${SCRIPT_DIR}/../mirror_data"

# 環境変数または引数で上書き可能
SOURCE_DIR="${1:-${UV_MIRROR_SOURCE:-$DEFAULT_SOURCE}}"
REMOTE_TARGET="${2:-${UV_MIRROR_REMOTE:-uvsync@linux-web-server:/var/www/uv-mirror}}"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "[ERROR] 同期元ディレクトリが見つかりません: $SOURCE_DIR" >&2
    echo "使い方: $0 [同期元フォルダパス] [uvsync@host:/var/www/uv-mirror]" >&2
    exit 1
fi

echo "=================================================================="
echo " uv ミラーデータの rsync 差分同期"
echo " 同期元 : ${SOURCE_DIR%/}/"
echo " 同期先 : ${REMOTE_TARGET%/}/"
echo "=================================================================="

# Windows (NTFS) から Linux へ rsync する際、パーミッションが 0700 等になって
# Nginx が 403 Forbidden を返すのを防ぐため --chmod を明示指定します。
rsync -rtvz --partial --progress \
    --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r \
    --exclude='.bin/' \
    --exclude='*.part' \
    --exclude='.DS_Store' \
    "${SOURCE_DIR%/}/" \
    "${REMOTE_TARGET%/}/"

echo ""
echo "[完了] Linux Web サーバーへの同期が完了しました！"
