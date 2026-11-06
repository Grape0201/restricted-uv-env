#!/usr/bin/env bash
# ==============================================================================
# setup_client_linux.sh
# 制限環境内の Linux クライアント端末に uv 本体・uv.toml・アップデートコマンドを
# インストール／更新するスクリプト。
#
# 使い方:
#   bash setup_client_linux.sh http://192.168.1.10
#   (または Web サーバーに配置して: curl -fsSL http://192.168.1.10/setup_client_linux.sh | bash -s -- http://192.168.1.10)
# ==============================================================================
set -euo pipefail

MIRROR_BASE_URL="${1:-${UV_MIRROR_URL:-}}"
if [[ -z "$MIRROR_BASE_URL" ]]; then
    echo "使い方: $0 <内部ミラーサーバーのURL (例: http://192.168.1.10)>" >&2
    exit 1
fi
MIRROR_BASE_URL="${MIRROR_BASE_URL%/}"

INSTALL_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/uv"
CONFIG_FILE="${CONFIG_DIR}/uv.toml"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"

echo "=================================================================="
echo " 制限環境向け uv セットアップ & アップデート (Linux)"
echo " ミラーサーバー: ${MIRROR_BASE_URL}"
echo "=================================================================="

# 1. サーバー上の最新バージョンを確認
SERVER_VER="$(curl -fsSL "${MIRROR_BASE_URL}/uv/version.txt" 2>/dev/null | tr -d '[:space:]' || true)"
CURRENT_VER=""
if [[ -x "${INSTALL_DIR}/uv" ]]; then
    CURRENT_VER="$("${INSTALL_DIR}/uv" --version | awk '{print $2}' || true)"
fi

if [[ -n "$SERVER_VER" && "$CURRENT_VER" == "$SERVER_VER" ]]; then
    echo "[1/3] uv は既に最新バージョン (${CURRENT_VER}) です。"
else
    echo "[1/3] uv バイナリ (${SERVER_VER:-latest}) をダウンロード・展開しています..."
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    ARCHIVE_URL="${MIRROR_BASE_URL}/uv/latest/uv-x86_64-unknown-linux-gnu.tar.gz"
    curl -fsSL "$ARCHIVE_URL" -o "${TMP_DIR}/uv.tar.gz"
    tar -xzf "${TMP_DIR}/uv.tar.gz" -C "$TMP_DIR"

    # アーカイブ直下またはサブディレクトリ内の uv / uvx を配置
    UV_BIN_FOUND="$(find "$TMP_DIR" -type f -name "uv" | head -n 1)"
    UVX_BIN_FOUND="$(find "$TMP_DIR" -type f -name "uvx" | head -n 1)"

    if [[ -z "$UV_BIN_FOUND" ]]; then
        echo "[ERROR] アーカイブ内に uv バイナリが見つかりませんでした。" >&2
        exit 1
    fi

    install -m 0755 "$UV_BIN_FOUND" "${INSTALL_DIR}/uv"
    if [[ -n "$UVX_BIN_FOUND" ]]; then
        install -m 0755 "$UVX_BIN_FOUND" "${INSTALL_DIR}/uvx"
    fi
    NEW_VER="$("${INSTALL_DIR}/uv" --version)"
    echo "  -> インストール完了: ${NEW_VER} (配置先: ${INSTALL_DIR}/uv)"
fi

# 2. uv.toml の生成・更新
echo "[2/3] uv 設定ファイル (${CONFIG_FILE}) を構成しています..."
cat > "$CONFIG_FILE" <<EOF
# ==============================================================================
# 制限環境向け uv グローバル設定 (自動生成)
# ==============================================================================

# 内部ミラーサーバーから python-build-standalone を取得
python-install-mirror = "${MIRROR_BASE_URL}/python"

# 内部ミラーサーバーのフラット Wheel 置き場をデフォルトインデックスとして使用（外部 PyPI への通信を無効化）
[[index]]
name = "internal-wheels"
url = "${MIRROR_BASE_URL}/wheels/"
format = "flat"
default = true
EOF
echo "  -> ${CONFIG_FILE} を更新しました"

# 3. いつでもワンコマンドで uv を最新版に更新できる uv-offline-update コマンドを作成
echo "[3/3] アップデート用コマンド (${INSTALL_DIR}/uv-offline-update) を作成しています..."
cat > "${INSTALL_DIR}/uv-offline-update" <<EOF
#!/usr/bin/env bash
set -euo pipefail
MIRROR_URL="\${1:-${MIRROR_BASE_URL}}"
MIRROR_URL="\${MIRROR_URL%/}"
INSTALL_DIR="${INSTALL_DIR}"

SERVER_VER="\$(curl -fsSL "\${MIRROR_URL}/uv/version.txt" | tr -d '[:space:]')"
CURRENT_VER="\$("\${INSTALL_DIR}/uv" --version 2>/dev/null | awk '{print \$2}' || echo 'none')"

echo "現在の uv バージョン : \${CURRENT_VER}"
echo "サーバーの最新バージョン: \${SERVER_VER}"

if [[ "\${CURRENT_VER}" == "\${SERVER_VER}" && "\${1:-}" != "--force" ]]; then
    echo "既に最新バージョンです！（強制再取得する場合は --force を指定）"
    exit 0
fi

echo "uv を \${SERVER_VER} へアップデートしています..."
TMP_DIR="\$(mktemp -d)"
trap 'rm -rf "\$TMP_DIR"' EXIT
curl -fsSL "\${MIRROR_URL}/uv/latest/uv-x86_64-unknown-linux-gnu.tar.gz" -o "\${TMP_DIR}/uv.tar.gz"
tar -xzf "\${TMP_DIR}/uv.tar.gz" -C "\$TMP_DIR"
install -m 0755 "\$(find "\$TMP_DIR" -type f -name "uv" | head -n 1)" "\${INSTALL_DIR}/uv"
UVX_FOUND="\$(find "\$TMP_DIR" -type f -name "uvx" | head -n 1)"
[[ -n "\$UVX_FOUND" ]] && install -m 0755 "\$UVX_FOUND" "\${INSTALL_DIR}/uvx"
echo "アップデート完了: \$("\${INSTALL_DIR}/uv" --version)"
EOF
chmod +x "${INSTALL_DIR}/uv-offline-update"

# PATH の確認
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "[案内] ~/.bashrc または ~/.zshrc に以下を追加して PATH を通してください:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "[完了] セットアップが完了しました！"
echo "  - Python のインストール : uv python install 3.12"
echo "  - uv 本体のアップデート : uv-offline-update"
