# dexec コマンドの使用方法

## 概要

`dexec` は Docker Swarm のコンテナ内で単一のコマンドを実行するコマンドです。シェルを開くのではなく、特定のコマンドの出力を取得する場合に便利です。

## 基本的な使用方法

```bash
dexec [オプション] <サービス名> <コマンド> ...
```

## オプション

| オプション | 説明 |
|-----------|------|
| `-1`      | 最初のレプリカで実行（デフォルト） |
| `-2`      | 2番目のレプリカで実行 |
| `-3`      | 3番目のレプリカで実行 |
| `-n`      | 非インタラクティブモード（出力のみ） |
| `-h`      | ヘルプを表示 |

## 使用例

### 1. コンテナ内でコマンドを実行

```bash
dexec myservice ls -la /app
```

`myservice` の最初のレプリカ内で `ls -la /app` を実行します。

### 2. ログを確認する

```bash
dexec myservice cat /var/log/application.log
```

### 3. 特定のレプリカで実行

```bash
dexec -2 myservice ps aux
```

2番目のレプリカ内で `ps aux` を実行します。

### 4. 非インタラクティブモード

```bash
dexec -n myservice echo "test"
```

出力のみを表示し、インタラクティブシェルを開きません。

## 実装の詳細

`dexec` は以下の処理を行います：

1. サービス名の検証
2. サービスが存在することを確認
3. 指定されたレプリカが利用可能かを確認
4. Docker コマンドを構築
5. リモート Docker ホストに接続してコマンドを実行

### Docker ホストへの接続

スクリプトは以下の環境変数を使用します：

```bash
export DOCKER_HOST="<node>.${HIVE_NAME}:2376"
export DOCKER_TLS=1
```

### サービス検出

複数のレプリカを持つサービスに対応するため、正確なサービスマッチングを行います。例えば、`dhcp` という名前は `dhcp` と `dhcpdb` の両方にマッチしないようにしています。

## トラブルシューティング

**エラー: "service X is not found"**
- サービス名が正確か確認してください
- `docker service ls` でサービス一覧を確認できます

**エラー: "the index X exceed the number of replicas"**
- 指定したレプリカ番号がサービスのレプリカ数以下であることを確認してください

**エラー: "the service X is not running"**
- サービスが起動していることを確認してください
- `docker service ps <service_name>` でサービスの状態を確認できます

## 関連コマンド

- `dsh`: インタラクティブシェルをコンテナ内に開く
- `dcp`: コンテナとホスト間でファイルをコピー
