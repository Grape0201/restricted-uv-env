# Ubuntu Linux サーバー構築・専用アカウント運用ガイド (Docker Compose + rsync)

制限環境内の Ubuntu サーバーに **Docker Compose** で Nginx 配信サーバーを常駐させ、**転送専用アカウント（`uvsync`）** を作成してセキュアに運用するための手順書です。

---

## 運用アーキテクチャ

```text
[ クライアント (Windows / Linux) ]
         │
         │ rsync (SSH 鍵認証)
         ▼
[ Ubuntu ホストサーバー ]
   受信ユーザー : uvsync (sudo権限なし・docker権限なしの最小権限)
   配置先      : /var/www/uv-mirror
         │
         │ バインドマウント (:ro 読み取り専用)
         ▼
[ Nginx コンテナ (Docker Compose) ] ── (HTTP :80) ──> [ 社内クライアント (uv) ]
```

* **安全な最小権限設計**:
  * `uvsync` アカウントには `sudo`（管理者）権限も `docker` 実行権限も**一切与えません**。
  * ファイルをホスト上のディレクトリに配置することだけに専念させます。
* **メンテナンスフリー**:
  * ホスト側のディレクトリがコンテナに読み取り専用（`:ro`）で直接マウントされるため、**rsync で差分ファイルが送られてきた瞬間に即座に Web 配信へ反映**されます。日々の同期でコンテナを再起動する必要はありません。

---

## サーバー構築手順（初回のみ）

> [!NOTE]
> 以下の手順は Ubuntu 20.04 LTS / 22.04 LTS / 24.04 LTS（Docker & Docker Compose インストール済み環境）を想定しています。
> サーバー管理者（root または sudo 権限を持つユーザー）が実施してください。

### Step 1: 配信用ディレクトリと転送専用アカウントの作成

```bash
# 1. 転送専用ユーザー uvsync を作成（パスワードログイン無効・sudoなし・dockerグループ所属なし）
sudo adduser --disabled-password --gecos "uv mirror sync user" uvsync

# 2. ホスト上の配信用ディレクトリを作成
sudo mkdir -p /var/www/uv-mirror

# 3. ディレクトリの所有者を uvsync に設定（パーミッション 755）
sudo chown -R uvsync:uvsync /var/www/uv-mirror
sudo chmod 755 /var/www/uv-mirror
```

---

### Step 2: SSH 鍵認証の設定（パスワードレス rsync 用）

クライアント端末（Windows / Linux）からパスワード入力なしで転送できるよう、公開鍵を `uvsync` に登録します。

#### 1. クライアント側で SSH 鍵を生成（未生成の場合のみ）
クライアント端末（Windows の PowerShell や Git Bash 等）で実行します：
```bash
ssh-keygen -t ed25519 -C "uv-mirror-sync"
# 全て Enter（パスフレーズなし、または任意で設定）
```
生成された公開鍵の中身（`~/.ssh/id_ed25519.pub`）をコピーします。

#### 2. Ubuntu サーバー側で公開鍵を登録
Ubuntu サーバー上で `uvsync` ユーザーの `authorized_keys` に追記します：
```bash
# .ssh ディレクトリを作成して権限を 700 に設定
sudo -u uvsync mkdir -p /home/uvsync/.ssh
sudo chmod 700 /home/uvsync/.ssh

# クライアントの公開鍵を追記（以下の "ssh-ed25519 AAAA..." 部分を実際の公開鍵に置き換えてください）
echo "ssh-ed25519 AAAA..." | sudo -u uvsync tee -a /home/uvsync/.ssh/authorized_keys

# authorized_keys の権限を 600 に設定
sudo chmod 600 /home/uvsync/.ssh/authorized_keys
```

---

### Step 3: Docker Compose で Nginx 配信コンテナを起動

本リポジトリの `deploy/` ディレクトリを使用してコンテナを起動します。

```bash
# deploy ディレクトリに移動
cd /path/to/restricted-uv-env/deploy

# 環境変数設定ファイルを作成
cp .env.example .env
```

`.env` を編集し、Step 1 で作成したディレクトリを指定します：
```ini
UV_MIRROR_PORT=80
UV_DATA_DIR=/var/www/uv-mirror
```

コンテナを起動します（`restart: unless-stopped` により、サーバー再起動時も自動復帰します）：
```bash
docker compose up -d
```

> **オフライン環境でイメージがない場合**:
> インターネット側の PC であらかじめ `docker pull nginx:alpine && docker save nginx:alpine -o nginx-alpine.tar` して Box 等で持ち込み、サーバー上で `docker load -i nginx-alpine.tar` してください。

> **ファイアウォール (UFW) を利用している場合**:
> ```bash
> sudo ufw allow 80/tcp
> ```

---

## 日常の同期テスト

クライアント端末から専用アカウント `uvsync` を指定して転送します。

* **Git Bash / WSL / Linux 端末から**:
  ```bash
  ./deploy/rsync_to_server.sh ./mirror_data uvsync@<LINUX_SERVER_IP>:/var/www/uv-mirror
  ```
* **Windows (PowerShell) から**:
  ```powershell
  .\deploy\rsync_to_server.ps1 -RemoteTarget "uvsync@<LINUX_SERVER_IP>:/var/www/uv-mirror"
  ```

※ スクリプト内で `--chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r` が自動付与されるため、ファイルは `0644`、ディレクトリは `0755` で配置され、コンテナ内の Nginx から即座に読み取り可能になります。

#### 動作確認
ブラウザまたは `curl` でアクセスします：
```bash
curl http://<LINUX_SERVER_IP>/uv/version.txt
curl http://<LINUX_SERVER_IP>/wheels/
```
ファイル一覧やバージョン番号が正常に取得できれば完了です。

---

## セキュリティ強化策（アドバンスド設定）

### 強化策 A: SSH 接続元 IP / サブネットを制限する

`uvsync` アカウントへの SSH 接続を社内サブネットや特定の管理 PC からのみに制限します。

Ubuntu サーバーの `/etc/ssh/sshd_config`（または `/etc/ssh/sshd_config.d/uvsync.conf`）に以下を追記します：

```text
# uvsync ユーザーは特定サブネットからのみ接続許可
Match User uvsync
    AllowUsers uvsync@192.168.1.* uvsync@10.0.*.*
    PasswordAuthentication no
    X11Forwarding no
    AllowTcpForwarding no
```

設定後、SSHD を再読み込みします：
```bash
sudo systemctl reload ssh
```

---

### 強化策 B: `rrsync` (Restricted rsync) による完全隔離

`uvsync` アカウントで SSH ログインした際、**`/var/www/uv-mirror` への書き込み専用 rsync 実行のみ**を許可し、通常のシェル操作や別ディレクトリへのアクセスを遮断します。

#### 1. `rrsync` コマンドの確認
```bash
# インストール済みか確認
which rrsync

# 見つからない場合は展開して配置
if [ ! -f /usr/bin/rrsync ] && [ -f /usr/share/doc/rsync/scripts/rrsync.gz ]; then
    sudo gzip -dc /usr/share/doc/rsync/scripts/rrsync.gz | sudo tee /usr/local/bin/rrsync > /dev/null
    sudo chmod +x /usr/local/bin/rrsync
fi
```

#### 2. `authorized_keys` に制限コマンドを追記
`/home/uvsync/.ssh/authorized_keys` の公開鍵行の先頭に `command="..."` を追加します：

```text
command="/usr/bin/rrsync -wo /var/www/uv-mirror",no-pty,no-agent-forwarding,no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA... uv-mirror-sync
```

* **オプション解説**:
  * `-wo`: 書き込み専用（Write-Only）。クライアントからサーバーへのアップロードのみ許可。
  * `/var/www/uv-mirror`: 対象ディレクトリをこのパス配下に限定。
  * `no-pty`: 仮想端末（対話的シェル）の割り当てを無効化。

> [!WARNING]
> `rrsync` を指定した場合、クライアント側の転送コマンドの宛先パスは `/var/www/uv-mirror` ではなく**相対パス（`.`）**を指定してください：
> ```bash
> ./deploy/rsync_to_server.sh ./mirror_data uvsync@<LINUX_SERVER_IP>:.
> ```

---

## トラブルシューティング

| 症状 | 原因 | 対処法 |
| :--- | :--- | :--- |
| **ブラウザで 403 Forbidden が出る** | ホスト側のディレクトリまたはファイルに読み取り権限がない | `sudo chmod 755 /var/www/uv-mirror`<br>`sudo chmod -R +r /var/www/uv-mirror` を実行。 |
| **SSH 接続時に `Permission denied (publickey)`** | `.ssh` や `authorized_keys` の所有者またはパーミッションの不一致 | `sudo chown -R uvsync:uvsync /home/uvsync/.ssh`<br>`sudo chmod 700 /home/uvsync/.ssh`<br>`sudo chmod 600 /home/uvsync/.ssh/authorized_keys` を確認。 |
| **rsync 時に `Permission denied`** | `uvsync` に `/var/www/uv-mirror` への書き込み権限がない | `sudo chown -R uvsync:uvsync /var/www/uv-mirror` を実行。 |
| **コンテナが起動しない** | ポート 80 が既に使用されている | `.env` で `UV_MIRROR_PORT=8080` など別のポート番号に変更して起動。 |
