---
name: docker-swarm-container-access
description: 'Manage and access Docker Swarm nodes and service containers. Use for debugging container issues, exploring container internals, running diagnostic commands, and retrieving logs. Covers SSH access to swarm nodes, interactive shell access (dsh), remote command execution (dexec), and file copying (dcp).'
argument-hint: 'Describe your debug task: e.g., "shell into the web service", "check logs in the app container", "copy database dump"'
user-invocable: true
---

# Docker Swarm コンテナアクセス

デバッグ時にサービスコンテナに潜り込んで調査する際に使用するワークフロー。本スキルはswarmノードへのSSH接続とコンテナアクセスの統合ガイドです。

## 使用場面

- **コンテナ内でのシェルアクセス**: 本番環境のコンテナに入り込んでリアルタイムにデバッグしたい
- **ログの確認と取得**: エラーログなどを確認・コピーしたい
- **設定の確認**: 実行中のコンテナの環境変数や設定を確認したい
- **一時的なコマンド実行**: シェルを開かずに単発コマンドを実行したい
- **ファイルの抽出**: コンテナ内のファイルをホストに取得したい

## アーキテクチャ概要

```
ホスト（開発環境）
    ↓
    └─ SSH → Swarm マネージャーノード（.hive/production/ssh_config）
        ↓
        └─ Docker Swarm
            ↓
            └─ サービスコンテナ（dsh, dexec, dcp で アクセス）
```

## クイックスタート

### 1. SSH で Swarm ノードにアクセス

```bash
ssh -F .hive/production/ssh_config <node_name>
```

SSH設定ファイル（`.hive/production/ssh_config`）は自動生成されており、ノードのホスト名やIPアドレスが定義されています。詳細は[SSH アクセス](./references/ssh-access.md)を参照。

### 2. コンテナ内にシェルを開く（最初のステップ）

ノードにSSH接続後またはノード内から、以下で対象サービスのコンテナにシェルアクセス：

```bash
dsh <service_name>
```

例：
```bash
dsh myapp
```

詳細は [dsh 使用方法](./references/dsh-usage.md) を参照。

### 3. 単発コマンドを実行

シェルを開かずにコマンドを実行したい場合：

```bash
dexec <service_name> <command>
```

例：
```bash
dexec myapp ps aux
dexec myapp cat /var/log/app.log
```

詳細は [dexec 使用方法](./references/dexec-usage.md) を参照。

### 4. ファイルをコピー

コンテナからホストへ、またはホストからコンテナへファイルをコピー：

```bash
# コンテナからホストへ
dcp <service_name>:<container_path> <host_path>

# ホストからコンテナへ
dcp <host_path> <service_name>:<container_path>
```

例：
```bash
dcp myapp:/var/log/app.log ./app.log
dcp ./config.yml myapp:/etc/config.yml
```

詳細は [dcp 使用方法](./references/dcp-usage.md) を参照。

## 段階的デバッグワークフロー

### ステップ 1: サービスの状態確認

```bash
# Swarm ノード内で
docker service ls
docker service ps <service_name>
```

### ステップ 2: コンテナに潜込むか単発コマンドか選択

**シェル作業が必要な場合**：
```bash
dsh <service_name>
# コンテナ内でログを確認、設定を変更、等々
```

**単発コマンドで済む場合**：
```bash
dexec <service_name> cat /var/log/app.log
dexec <service_name> env
```

### ステップ 3: ログやファイルの取得

```bash
dcp <service_name>:/var/log/app.log ./debug-logs/
```

### ステップ 4: 複数レプリカのチェック

複数レプリカがある場合、各レプリカを確認：

```bash
dsh -1 <service_name>  # 最初のレプリカ
dsh -2 <service_name>  # 2番目のレプリカ
```

## よくある使用例

### アプリケーションのエラーログを確認したい

```bash
# ホスト上で
dexec myapp tail -f /var/log/application.log
```

### ヘルスチェックの詳細を知りたい

```bash
dsh myapp
# コンテナ内で
curl localhost:8080/health
```

### データベース接続をテストしたい

```bash
dexec myapp curl http://postgres:5432/
```

### 環境変数を確認したい

```bash
dexec myapp env | grep DATABASE
```

### ログをホストにダウンロードしたい

```bash
dcp myapp:/var/log/app.log ./local-debug.log
```

## トラブルシューティング

### "SSH connection refused" エラー

1. SSH設定ファイルが存在するか確認：
   ```bash
   ls -la .hive/production/ssh_config
   ```
2. SSH キーが正しく設定されているか確認
3. Swarm ノードが起動しているか確認

### "service X is not found" エラー

1. サービス名が正確か確認：
   ```bash
   docker service ls
   ```
2. サービスが実際に存在するか確認
3. タイプミスがないか確認（大文字小文字など）

### "docker: command not found" エラー

コンテナ内に Docker がインストールされていない可能性があります。単発コマンドを実行して確認：
```bash
dexec <service_name> which docker
```

### 複数レプリカの場合、別のレプリカにアクセスしたい

オプション `-1`, `-2`, `-3` を使用：
```bash
dsh -2 myapp    # 2番目のレプリカにアクセス
dexec -3 myapp ps aux  # 3番目のレプリカでコマンド実行
```

## 関連リソース

- [SSH アクセス詳細](./references/ssh-access.md)
- [dsh コマンド詳細](./references/dsh-usage.md)
- [dexec コマンド詳細](./references/dexec-usage.md)
- [dcp コマンド詳細](./references/dcp-usage.md)

## 注意事項

- `.hive/production/ssh_config` はデプロイ時に自動生成されるため、本ファイルは `.gitignore` に登録されています

- `dsh`、`dexec`、`dcp` はすべての Swarm ノードに事前に配置済みです

- Docker TLS が有効な環境でのアクセスを前提としています（`DOCKER_TLS=1`）

- サービス名のマッチングは正確です。例えば `dhcp` を指定すると `dhcpdb` にはマッチしません
