# Swarm ノードへの SSH アクセス

## 概要

Docker Swarm の各ノードには SSH でアクセスできます。SSH 設定ファイルは自動生成されます。

## SSH 接続方法

### 1. SSH 設定ファイルの確認

```bash
cat .hive/production/ssh_config
```

このファイルは自動生成されており、各 Swarm ノードのアクセス情報を含みます。

### 2. ノードへの SSH 接続

```bash
ssh -F .hive/production/ssh_config <node_name>
```

例：
```bash
ssh -F .hive/production/ssh_config hive-node-1
```

### 3. 便利なエイリアス設定

以下をシェル設定ファイル（`.bashrc` など）に追加することで、より簡潔に実行できます：

```bash
alias sshive="ssh -F .hive/production/ssh_config"
```

その後は以下のように実行：
```bash
sshive hive-node-1
```

## ノードの確認

```bash
ssh -F .hive/production/ssh_config <node_name> "docker node ls"
```

SSH 接続が成功すると、Docker Swarm のコマンドを実行できます。

## 注意事項

- `.hive/production/ssh_config` はデプロイ時に自動生成されます
- ファイルが存在しない場合は、デプロイ処理を確認してください
- 本ファイルは `.gitignore` に登録されており、リポジトリには含まれません
