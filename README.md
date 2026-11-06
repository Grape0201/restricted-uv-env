# 制限環境向け `uv` オフライン基盤ツールキット (Box + 静的 Web 配信方式)

`devpi` のような複雑な PyPI サーバーを使わず、**Box 同期フォルダ**と**制限環境内の Linux Web サーバー (Nginx 等)** だけで、Windows / Linux 両対応の `uv` 環境を構築・維持するためのツールキットです。

---

## 特長

1. **`devpi` 不要（置くだけ運用）**
   * Nginx の `autoindex on;` で `.whl` フォルダを公開し、`uv.toml` の `format = "flat"` (`default = true`) で参照するため、ファイルを `rsync` で配置するだけで `uv add` / `uv lock` / `uv sync` が動作します。
2. **Windows / Linux 両用 Wheel の一括自動収集**
   * インターネット側の Windows PC で `sync_to_box.py`（または `run_sync.bat`）を実行するだけで、Windows (`win_amd64`) 用と Linux (`manylinux*_x86_64`) 用の全依存 `.whl` を自動解決して Box に差分ダウンロードします。
3. **`python-build-standalone` の完全自動一致**
   * 取得した `uv` バイナリ自身が要求する正確なビルドタグの CPython ランタイムを自動抽出し、`uv python install 3.12` がそのまま動くディレクトリ構造で保存します。
4. **社内プロキシ & Zscaler 証明書対応**
   * `use_system_certs = true` により、Windows の OS 証明書ストアに導入された Zscaler ルート証明書やシステムプロキシ設定を `uv` と Python の両方で自動認識します。
5. **制限環境内での `uv` 最新版アップデート対応**
   * 収集時に最新版の `uv` 本体を自動取得し、制限環境内の各端末では `uv-offline-update` コマンド一発で内部サーバー上の最新 `uv` へアップデートできます。

---

## ファイル構成

```text
restricted-uv-env/
├── config.toml                 # 収集設定ファイル（プロキシ/Zscaler、Pythonバージョン、パッケージ一覧）
├── sync_to_box.py              # [外部Win用] uv本体・Pythonランタイム・Win/Linux両用Wheelの差分収集スクリプト
├── run_sync.bat                # [外部Win用] ダブルクリック実行用バッチファイル
├── deploy/
│   ├── Dockerfile              # [内部Linuxサーバー用] Nginx コンテナ用 Dockerfile
│   ├── docker-compose.yml      # [内部Linuxサーバー用] docker compose up -d で起動する Compose 定義
│   ├── .env.example            # [内部Linuxサーバー用] ポートやデータディレクトリの設定例
│   ├── nginx-uv-mirror.conf    # [内部Linuxサーバー用] Nginx 設定ファイル (autoindex on)
│   ├── rsync_to_server.sh      # [内部Win(Git Bash/WSL)/Linux用] BoxからLinuxサーバーへの rsync 差分転送
│   ├── rsync_to_server.ps1     # [内部Win(PowerShell)用] BoxからLinuxサーバーへの rsync 差分転送
│   ├── setup_client_linux.sh   # [内部Linux端末用] uv 導入・uv.toml 設定・uv-offline-update 作成
│   └── setup_client_win.ps1    # [内部Win端末用] uv 導入・uv.toml 設定・uv-offline-update 作成
└── README.md                   # 本手順書
```

---

## 初期構築手順

### Step 1: インターネット側 Windows PC で Box へ資材を収集する

1. このフォルダ一式を Box 同期フォルダ内（例: `C:\Users\<User>\Box\restricted-uv-env`）に配置します。
2. [`config.toml`](file:///Users/shotaro/work/restricted-uv-env/config.toml) を開き、必要に応じて編集します。
   * **Zscaler / プロキシ設定 (`[network]`)**:
     * Windows の証明書ストアに Zscaler 証明書が入っている場合はデフォルト（`use_system_certs = true`）のままで動作します。
     * `.pem` ファイルを明示指定したい場合は `ca_bundle = "C:/path/to/zscaler.pem"` を設定してください。
     * プロキシが自動検出されない場合は `https_proxy = "http://proxy.example.com:8080"` を記入してください。
   * **パッケージ追加 (`[packages]`)**:
     * `include` リストに欲しいパッケージ名、または `requirement_files` にプロジェクトの `pyproject.toml` / `requirements.txt` のパスを指定します。
3. [`run_sync.bat`](file:///Users/shotaro/work/restricted-uv-env/run_sync.bat) をダブルクリック（またはターミナルで `uv run --system-certs sync_to_box.py`）します。
4. `mirror_data/` フォルダ内に以下の構成でファイルが差分ダウンロードされ、Box 経由で制限環境側へ自動同期されます。
   ```text
   mirror_data/
   ├── uv/
   │   ├── version.txt
   │   └── latest/
   │       ├── uv-x86_64-pc-windows-msvc.zip
   │       └── uv-x86_64-unknown-linux-gnu.tar.gz
   ├── python/
   │   └── <ビルドタグ>/cpython-3.12.x+...tar.gz
   └── wheels/
       └── *.whl (Windows用・Linux用・共通Wheel)
   ```

---

### Step 2: 制限環境内の Linux Web サーバーを設定する（初回のみ）

Linux サーバー上での Nginx 構築は、**Docker Compose を使う方法（推奨）** と **ホストに直接インストールする方法** のどちらでも利用可能です。

#### 方法 A: Docker Compose を使う場合（推奨）
ホスト環境を汚さずに `autoindex on;` を含んだミラー配信コンテナを即座に起動できます。

1. `deploy/` ディレクトリに移動します：
   ```bash
   cd deploy
   ```
2. （任意）ポート番号（デフォルト 80）やデータマウント元（デフォルト `../mirror_data`）を変更したい場合は `.env` を作成します：
   ```bash
   cp .env.example .env
   # 必要に応じて vi .env で編集 (例: UV_DATA_DIR=/var/www/uv-mirror)
   ```
3. コンテナを起動します：
   ```bash
   docker compose up -d
   ```
   ※ オフライン環境でビルド用イメージ（`nginx:alpine`）がない場合は、インターネット側 PC であらかじめ `docker pull nginx:alpine && docker save nginx:alpine -o nginx-alpine.tar` して Box 経由で持ち込み、`docker load -i nginx-alpine.tar` しておくと安心です。

#### 方法 B: ホストに直接 Nginx をインストールする場合
1. Linux Web サーバー上で公開用ディレクトリを作成します：
   ```bash
   sudo mkdir -p /var/www/uv-mirror
   sudo chown -R $USER:$USER /var/www/uv-mirror
   ```
2. [`deploy/nginx-uv-mirror.conf`](file:///Users/shotaro/work/restricted-uv-env/deploy/nginx-uv-mirror.conf) を `/etc/nginx/conf.d/uv-mirror.conf`（Ubuntu 等の場合は `/etc/nginx/sites-enabled/uv-mirror`）に配置し、Nginx をリロードします：
   ```bash
   sudo cp deploy/nginx-uv-mirror.conf /etc/nginx/conf.d/uv-mirror.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

---

### Step 3: 制限環境内の Windows PC から Linux Web サーバーへ `rsync` する

Box の同期が完了したら、制限環境内の Windows PC から `rsync` で Linux Web サーバーへ差分転送します。

* **Git Bash / WSL から実行する場合**:
  ```bash
  ./deploy/rsync_to_server.sh ./mirror_data user@<LINUX_SERVER_IP>:/var/www/uv-mirror
  ```
* **PowerShell から実行する場合**:
  ```powershell
  .\deploy\rsync_to_server.ps1 -RemoteTarget "user@<LINUX_SERVER_IP>:/var/www/uv-mirror"
  ```
  ※ `--chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r` が自動付与されるため、Windows からの転送でも Nginx で権限エラー（403 Forbidden）になりません。

---

### Step 4: 制限環境内の各クライアント端末（Windows / Linux）をセットアップする

各開発端末で1回だけ以下のスクリプトを実行します。

* **Linux 端末の場合**:
  ```bash
  bash deploy/setup_client_linux.sh http://<LINUX_SERVER_IP>
  ```
* **Windows 端末の場合 (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\deploy\setup_client_win.ps1 -MirrorBaseUrl "http://<LINUX_SERVER_IP>"
  ```

これで `~/.config/uv/uv.toml`（Windows は `%APPDATA%\uv\uv.toml`）が自動構成され、以降は特別なオプションなしで通常の `uv` コマンドが使えます！

```bash
# Python ランタイムのインストール（内部サーバーから数秒で完了）
uv python install 3.12

# プロジェクト作成とパッケージ追加（内部サーバーの wheels/ から自動解決）
uv init my-project
cd my-project
uv add requests numpy pandas

# 仮想環境の同期とコマンド実行
uv sync
uv run pytest
```

---

## 日常の運用フロー

### パッケージを追加したいとき
1. インターネット側 Windows PC で `config.toml` の `[packages] include` にパッケージ名を追記する。
2. `run_sync.bat` を実行する（増えた差分の `.whl` だけが数秒で Box にダウンロードされます）。
3. 制限環境側 Windows PC で `rsync_to_server` を実行する（差分だけが Linux サーバーへ転送され、即座に全端末から `uv add` 可能になります）。

### `uv` 本体を最新バージョンにアップデートしたいとき
1. `config.toml` の `[uv] target_version = "latest"` の状態で、インターネット側 Windows PC で `run_sync.bat` を実行する。
   * 最新版の `uv` バイナリ（Windows/Linux）と、**その最新 `uv` が要求する新しい `python-build-standalone` ランタイム**がセットで自動取得されます。
2. 制限環境側で `rsync_to_server` を実行し、Linux Web サーバーを更新する。
3. 制限環境内の各クライアント端末（Windows / Linux 共通）で以下のコマンドを実行する：
   ```bash
   uv-offline-update
   ```
   内部サーバーの `/uv/version.txt` を確認し、数秒で手元の `uv` / `uvx` が最新版にアップデートされます。
