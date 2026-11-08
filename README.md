# 制限環境向け `uv` オフライン基盤ツールキット (Box + 静的 Web 配信方式)

`devpi` のような複雑な PyPI サーバーを使わず、**Box 同期フォルダ**と**制限環境内の Linux Web サーバー (Nginx 等)** だけで、Windows / Linux 両対応の `uv` 環境を構築・維持するためのツールキットです。

---

## 特長

1. **`devpi` 不要（置くだけ運用）**
   * Nginx の `autoindex on;` で `.whl` フォルダを公開し、`uv.toml` の `format = "flat"` (`default = true`) で参照するため、ファイルを `xcopy` や `rsync` で配置するだけで `uv add` / `uv lock` / `uv sync` が動作します。
2. **Windows / Linux 両用 Wheel の一括自動収集**
   * インターネット側の Windows PC で `sync_to_box.py`（または `run_sync.bat`）を実行するだけで、Windows (`win_amd64`) 用と Linux (`manylinux*_x86_64`) 用の全依存 `.whl` を自動解決して Box に差分ダウンロードします。
3. **`python-build-standalone` の完全自動一致**
   * 取得した `uv` バイナリ自身が要求する正確なビルドタグの CPython ランタイムを自動抽出し、`uv python install 3.12` がそのまま動くディレクトリ構造で保存します。
4. **社内プロキシ & Zscaler 証明書対応**
   * `use_system_certs = true` により、Windows の OS 証明書ストアに導入された Zscaler ルート証明書やシステムプロキシ設定を `uv` と Python の両方で自動認識します。
5. **Windows 標準の `xcopy` 対応（追加ツール不要）**
   * 制限環境の Windows PC に `rsync.exe` がインストールされていなくても、OS 標準搭載の `xcopy` コマンドだけで Linux サーバーへの差分転送が完了します。
6. **制限環境内での `uv` 最新版アップデート対応**
   * 収集時に最新版の `uv` 本体を自動取得し、制限環境内の各端末では `uv-offline-update` コマンド一発で内部サーバー上の最新 `uv` へアップデートできます。
7. **収集時の脆弱性チェック (`pip-audit` 相当)**
   * 解決した全パッケージを [OSV](https://osv.dev) に照会し、既知の脆弱性と修正版を報告します（結果は `mirror_data/audit_report.json` にも保存）。

---

## ディレクトリ・ファイル構成

手順ごとに `step-1` 〜 `step-4` に分割されています。

```text
restricted-uv-env/
├── mirror_data/                     # 収集資材（自動生成・Box同期）
│   ├── uv/                          # uv バイナリ (Windows/Linux)
│   ├── python/                      # CPython ランタイム (各バージョン)
│   └── wheels/                      # 依存 Wheel 一式 (Win/Linux両用)
│
├── step-1/                          # [外部Win] Boxへの資材収集
│   ├── config.toml                  # 収集設定（プロキシ/Zscaler、Pythonバージョン、パッケージ一覧）
│   ├── sync_to_box.py               # uv本体・Pythonランタイム・Wheelの差分収集スクリプト
│   └── run_sync.bat                 # ダブルクリック実行用バッチファイル
│
├── step-2/                          # [内部Linux] Webサーバー構築 (Docker Compose)
│   ├── Dockerfile                   # Nginx コンテナ用 Dockerfile
│   ├── docker-compose.yml           # docker compose up -d で起動する Compose 定義
│   ├── .env.example                 # ポートやデータディレクトリの設定例
│   ├── nginx-uv-mirror.conf         # Nginx 設定ファイル (autoindex on)
│   └── ubuntu_server_setup.md       # Ubuntu 向け専用アカウント・Samba(SMB)/SSH設定手順書
│
├── step-3/                          # [内部Win] Linuxサーバーへの資材転送 (xcopy)
│   ├── copy_to_server.bat           # [Windows標準] xcopy コマンドによる差分転送バッチ
│   ├── copy_to_server.ps1           # [PowerShell] xcopy コマンドによる差分転送スクリプト
│   └── rsync_to_server.sh           # [Linux/WSL用] rsync による差分転送スクリプト
│
├── step-4/                          # [内部端末] クライアント環境セットアップ
│   ├── setup_client_win.bat         # [内部Win端末用] ダブルクリック実行用バッチ
│   ├── setup_client_win.ps1         # [内部Win端末用] uv 導入・uv.toml 設定・uv-offline-update 作成
│   └── setup_client_linux.sh        # [内部Linux端末用] uv 導入・uv.toml 設定・uv-offline-update 作成
│
└── README.md                        # 本手順書
```

---

## 初期構築手順

```mermaid
flowchart TD
    subgraph Step1["Step 1: インターネット側 Windows PC"]
        A["step-1/run_sync.bat 実行"] --> B["mirror_data/ へ資材収集"]
    end
    B -->|Box 自動同期| C["制限環境内 Windows PC"]
    subgraph Step2["Step 2: 制限環境内 Linux Web サーバー"]
        D["step-2/ で Docker Compose 起動 & Samba 共有設定"]
    end
    subgraph Step3["Step 3: 資材転送"]
        C -->|step-3/copy_to_server.bat (xcopy)| D
    end
    subgraph Step4["Step 4: 制限環境内 クライアント端末"]
        D -->|HTTP 配信| E["step-4/setup_client_win.bat<br>または setup_client_linux.sh"]
    end
```

### Step 1: インターネット側 Windows PC で Box へ資材を収集する

1. このフォルダ一式を Box 同期フォルダ内（例: `C:\Users\<User>\Box\restricted-uv-env`）に配置します。
2. [`step-1/config.toml`](step-1/config.toml) を開き、必要に応じて編集します。
   * **Zscaler / プロキシ設定 (`[network]`)**:
     * Windows の証明書ストアに Zscaler 証明書が入っている場合はデフォルト（`use_system_certs = true`）のままで動作します。
     * `.pem` ファイルを明示指定したい場合は `ca_bundle = "C:/path/to/zscaler.pem"` を設定してください。
     * プロキシが自動検出されない場合は `https_proxy = "http://proxy.example.com:8080"` を記入してください。
   * **パッケージ追加 (`[packages]`)**:
     * `include` リストに欲しいパッケージ名、または `requirement_files` にプロジェクトの `pyproject.toml` / `requirements.txt` のパスを指定します。
   * **脆弱性チェック (`[audit]`)**:
     * デフォルト（`enabled = true`）で、Wheel 取得前に解決済みパッケージを OSV に照会し、脆弱性を報告します（`pip-audit` 相当）。
     * `fail_on_vulnerability = true` にすると、脆弱性検出時に Wheel を取得せず中断します。
     * 誤検知や許容する脆弱性は `ignore_ids = ["GHSA-xxxx", "CVE-xxxx"]` で除外できます。
     * OSV に接続できない場合は警告のみで続行します（`fail_on_vulnerability = true` の場合は中断）。
     * 対象は収集した Python パッケージのみで、`uv` 本体や Python ランタイムは対象外です。
3. [`step-1/run_sync.bat`](step-1/run_sync.bat) をダブルクリック（またはターミナルで `cd step-1 && uv run --system-certs sync_to_box.py -c config.toml`）します。
4. プロジェクト直下の `mirror_data/` フォルダ内に以下の構成でファイルが差分ダウンロードされ、Box 経由で制限環境側へ自動同期されます。
   ```text
   mirror_data/
   ├── uv/
   │   ├── version.txt
   │   └── latest/
   │       ├── uv-x86_64-pc-windows-msvc.zip
   │       └── uv-x86_64-unknown-linux-gnu.tar.gz
   ├── python/
   │   └── <ビルドタグ>/cpython-3.12.x+...tar.gz
   ├── wheels/
   │   └── *.whl (Windows用・Linux用・共通Wheel)
   └── audit_report.json (脆弱性チェック結果)
   ```

---

### Step 2: 制限環境内の Linux Web サーバーを設定する（初回のみ）

ホスト環境を汚さず、安全かつ簡単に運用するため **Docker Compose** で Nginx 配信サーバーを起動します。

> [!TIP]
> 本番運用で推奨される **専用アカウント（`uvsync`）の作成**、**Windows からの xcopy 受信用 Samba (SMB) 共有設定**、SSH 鍵設定、IP制限、`rrsync` 隔離の詳細手順は、**[`step-2/ubuntu_server_setup.md`](step-2/ubuntu_server_setup.md)** を参照してください。

#### クイックスタート手順

1. **配信用ディレクトリの準備**:
   サーバー上で受信用ディレクトリを作成します：
   ```bash
   sudo mkdir -p /var/www/uv-mirror
   sudo chown -R $USER:$USER /var/www/uv-mirror
   sudo chmod 755 /var/www/uv-mirror
   ```

2. **設定ファイル（`.env`）の準備**:
   `step-2/` ディレクトリに移動し、`.env` を作成してマウント先を指定します：
   ```bash
   cd step-2
   cp .env.example .env
   # vi .env 等で UV_DATA_DIR=/var/www/uv-mirror に設定
   ```

3. **コンテナの起動**:
   ```bash
   docker compose up -d
   ```
   * `restart: unless-stopped` が設定されているため、サーバー再起動時も自動的に立ち上がります。
   * ホスト側のディレクトリがコンテナに読み取り専用（`:ro`）でマウントされるため、**日々のファイル同期のたびにコンテナを再起動する必要はありません**。

   ※ オフライン環境でビルド用イメージ（`nginx:alpine`）がない場合は、インターネット側 PC であらかじめ `docker pull nginx:alpine && docker save nginx:alpine -o nginx-alpine.tar` して Box 経由で持ち込み、`docker load -i nginx-alpine.tar` しておくと安心です。

4. **Samba 共有の設定（Windows から xcopy で転送する場合）**:
   Windows PC から Linux サーバーへ直接 `xcopy` 転送できるようにするため、Samba で受信用ディレクトリを共有します。
   （詳細は [`step-2/ubuntu_server_setup.md`](step-2/ubuntu_server_setup.md) の Step 2-A を参照）
   ```bash
   sudo apt update && sudo apt install -y samba
   sudo smbpasswd -a $USER
   # /etc/samba/smb.conf に [uv-mirror] 共有セクションを追加して再起動
   sudo systemctl restart smbd
   ```

---

### Step 3: 制限環境内の Windows PC から Linux Web サーバーへ `xcopy` する

Box の同期が完了したら、制限環境内の Windows PC から Linux Web サーバーへ差分転送します。
制限環境の Windows PC には `rsync.exe` がない場合が多いため、**Windows 標準コマンドの `xcopy`** を使用します。

#### 方法 A: バッチファイルで実行する場合（推奨・追加ツール不要）

[`step-3/copy_to_server.bat`](step-3/copy_to_server.bat) をダブルクリックするか、コマンドプロンプトから引数を指定して実行します：

```cmd
.\step-3\copy_to_server.bat "\\<LINUX_SERVER_IP>\uv-mirror"
```
（またはネットワークドライブ `Z:\` に割り当てている場合は `.\step-3\copy_to_server.bat "Z:\"`）

※ 引数なしでダブルクリックした場合は、対話画面で転送先パスの入力を求められます。
※ 内部で `xcopy /E /I /Y /D /C /H /R` を呼び出し、更新された差分ファイルのみを安全に転送します。

#### 方法 B: PowerShell から実行する場合

PowerShell を利用したい場合は [`step-3/copy_to_server.ps1`](step-3/copy_to_server.ps1) を使用します：

```powershell
powershell -ExecutionPolicy Bypass -File .\step-3\copy_to_server.ps1 -Destination "\\<LINUX_SERVER_IP>\uv-mirror"
```

#### （参考）Linux / WSL / Git Bash 端末から転送する場合

Linux 端末や Git Bash / WSL 環境から転送する場合は、従来の `rsync` スクリプトも利用可能です：

```bash
./step-3/rsync_to_server.sh ./mirror_data uvsync@<LINUX_SERVER_IP>:/var/www/uv-mirror
```

---

### Step 4: 制限環境内の各クライアント端末（Windows / Linux）をセットアップする

各開発端末で1回だけセットアップスクリプトを実行します。

* **Windows 端末の場合 (バッチ実行 / 推奨)**:
  [`step-4/setup_client_win.bat`](step-4/setup_client_win.bat) をダブルクリック、またはコマンドプロンプトから実行します：
  ```cmd
  .\step-4\setup_client_win.bat http://<LINUX_SERVER_IP>
  ```
  PowerShell で直接実行する場合:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\step-4\setup_client_win.ps1 -MirrorBaseUrl "http://<LINUX_SERVER_IP>"
  ```

* **Linux 端末の場合**:
  ```bash
  bash step-4/setup_client_linux.sh http://<LINUX_SERVER_IP>
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
1. インターネット側 Windows PC で [`step-1/config.toml`](step-1/config.toml) の `[packages] include` にパッケージ名を追記する。
2. [`step-1/run_sync.bat`](step-1/run_sync.bat) を実行する（増えた差分の `.whl` だけが数秒で Box にダウンロードされます）。
3. 制限環境側 Windows PC で [`step-3/copy_to_server.bat`](step-3/copy_to_server.bat) を実行する（`xcopy` で差分だけが Linux サーバーへ転送され、即座に全端末から `uv add` 可能になります）。

### `uv` 本体を最新バージョンにアップデートしたいとき
1. [`step-1/config.toml`](step-1/config.toml) の `[uv] target_version = "latest"` の状態で、インターネット側 Windows PC で [`step-1/run_sync.bat`](step-1/run_sync.bat) を実行する。
   * 最新版の `uv` バイナリ（Windows/Linux）と、**その最新 `uv` が要求する新しい `python-build-standalone` ランタイム**がセットで自動取得されます。
2. 制限環境側で [`step-3/copy_to_server.bat`](step-3/copy_to_server.bat) を実行し、Linux Web サーバーを更新する。
3. 制限環境内の各クライアント端末（Windows / Linux 共通）で以下のコマンドを実行する：
   ```bash
   uv-offline-update
   ```
   内部サーバーの `/uv/version.txt` を確認し、数秒で手元の `uv` / `uvx` が最新版にアップデートされます。
