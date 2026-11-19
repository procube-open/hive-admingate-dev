# Web アクセス

このドキュメントは、**Web アクセス制限機能** を環境に適用・反映するための手順書です。

## 機能

以下の 2 つの機能を個別に有効化できます。**既定では両方とも無効 (`false`)** のため、ブランチを取り込んだだけでは通信への影響はありません。

| 機能 | 有効化フラグ | 適用先と仕組み |
| --- | --- | --- |
| **日本国外からのアクセス制限（国別制限）** | `hive_web_access_guard_country_enabled` | 各 hive ホストの `iptables` / `ip6tables` (`mangle/PREROUTING`) と `ipset` により、日本向け CIDR（IPv4/IPv6）に含まれない送信元からの新規接続を拒否します。 |
| **DDoS 緩和** | `hive_web_access_guard_ddos_enabled` | ① 各 hive ホストで送信元 IP ごとの新規接続レート・同時接続数を制限し、② OIDC コンテナ（Nginx）でインスタンス全体のリクエストレート・同時接続数・タイムアウトを制限します。 |

どちらか片方だけを有効にすることも可能です。DDoS 緩和だけを有効にする場合、CIDR ファイルの配置や `ipset` のインストールは不要です。

> **なぜホスト側（iptables/ipset）で制限するのか**
> Docker Swarm ingress は Nginx に到達する前に送信元 IP を変換するため、Nginx 単体（GeoIP2 等）では本来のクライアント IP を判定できません。そのため、国別制限と IP 単位の接続制限は hive ホストの `mangle/PREROUTING` で行い、Nginx 側はインスタンス全体に対する補助制限として動作します。

### 制約

- **対象は TCP のみ**: HTTP/3 などの UDP Web 公開は保護対象になりません（別途対応が必要です）。DNS や Socket Warp の UDP ポートは対象に含めないでください。
- **新規接続のみ対象**: すでに確立済みの接続は、適用しても切断されません。
- **国別データはリポジトリに含まれない**: GeoIP / CIDR データの提供元、利用条件、更新方法は運用側で決定し、mother 環境へ配置する必要があります。
- **制限の限界**: 国情報には誤判定があり、VPN・プロキシ経由の実際の所在地は保証できません。また、回線飽和を引き起こす大規模分散攻撃はこの構成だけでは防げません。

---

## 適用・反映の全体フロー

1. [事前確認](#1-事前確認)（対象ポート・インターフェース・前提サービスの確認）
2. [日本向け CIDR ファイルの準備](#2-日本向け-cidr-ファイルの準備国別制限を使う場合のみ)（mother 環境への配置）
3. [設定の編集](#3-設定の編集)（`inventory/group_vars/all.yml` 等の更新）
4. [反映コマンドの実行](#4-反映コマンドの実行)（`hive` コマンドで反映・再起動不要）
5. [反映後の確認](#5-反映後の確認)（ルール・Nginx 設定・疎通の確認）

---

## 1. 事前確認

適用前に、対象環境で以下を確認してください。

- **保護対象の TCP ポート**: 現行 inventory の Web 公開ポート候補は TCP `80`, `443` です。ステージやセキュリティグループの設定を確認し、ほかにインターネットへ直接公開している TCP Web ポートがあれば対象に追加してください。UDP ポートは指定しないでください。
- **外部ネットワークインターフェース**: hive ホストの外部向けインターフェース名を確認してください（現行 AWS 構成では `eth0`）。
- **ファイアウォールサービスの稼働**: 各 hive ホストで `iptables.service` と `ip6tables.service` が起動済みである必要があります（未起動の場合、反映タスクは失敗して停止します）。

---

## 2. 日本向け CIDR ファイルの準備（国別制限を使う場合のみ）

DDoS 緩和のみを使う場合は、この手順をスキップして「[3. 設定の編集](#3-設定の編集)」へ進んでください。

国別制限を有効にする場合、日本向け CIDR ファイルを **IPv4 / IPv6 の両方** 用意し、**hive ホストではなく `hive` コマンドを実行する mother 環境**（Codespaces を利用している場合は開発コンテナ内）に配置します。

### IPdeny のデータを取り込む例

IPdeny の日本向け集約リストを利用する場合は、mother 環境で以下を実行します。両方のダウンロード完了後に、設定例と同じ `/etc/hive/geoip/` へ配置します。

```sh
(
  set -eu
  tmp_dir=$(mktemp -d)
  trap 'rm -f "$tmp_dir/jp-ipv4.cidrs" "$tmp_dir/jp-ipv6.cidrs"; rmdir "$tmp_dir"' EXIT

  curl -fsSL https://www.ipdeny.com/ipblocks/data/aggregated/jp-aggregated.zone \
    -o "$tmp_dir/jp-ipv4.cidrs"
  sleep 1
  curl -fsSL https://www.ipdeny.com/ipv6/ipaddresses/aggregated/jp-aggregated.zone \
    -o "$tmp_dir/jp-ipv6.cidrs"
  test -s "$tmp_dir/jp-ipv4.cidrs"
  test -s "$tmp_dir/jp-ipv6.cidrs"

  sudo install -d -m 0755 /etc/hive/geoip
  sudo install -m 0644 "$tmp_dir/jp-ipv4.cidrs" "$tmp_dir/jp-ipv6.cidrs" /etc/hive/geoip/
)
```

> ファイルを配置しただけでは制限は有効になりません。利用前に [IPdeny の利用条件](https://www.ipdeny.com/tos.php) を確認してください。

---

## 3. 設定の編集

全ステージ共通の設定項目が `inventory/group_vars/all.yml` に用意されています（既定は両方 `false`）。
有効にしたい機能のフラグを `true` に変更し、必要に応じて各パラメータを調整してください。特定ステージのみに適用したい場合は、対象ステージの変数で上書きしてください。

### 検証済みの設定例

一時適用試験で動作確認した設定値です（ホスト側の対象は TCP 80/443。直接公開ポートも制限する場合は `hive_web_access_guard_ports` に追加してください）。

```yaml
# 共通設定（対象インターフェース・TCP ポート）
hive_web_access_guard_interfaces: [eth0]
hive_web_access_guard_ports: [80, 443]

# 国別制限（日本国外からのアクセス拒否）
hive_web_access_guard_country_enabled: true
hive_web_access_guard_ipv4_cidrs_file: /etc/hive/geoip/jp-ipv4.cidrs
hive_web_access_guard_ipv6_cidrs_file: /etc/hive/geoip/jp-ipv6.cidrs
hive_web_access_guard_ipv4_min_networks: 1
hive_web_access_guard_ipv6_min_networks: 1
hive_web_access_guard_min_update_ratio: 0.8

# DDoS 緩和（ホスト側の接続制限）
hive_web_access_guard_ddos_enabled: true
hive_web_access_guard_new_connections_per_second: 20
hive_web_access_guard_new_connections_burst: 40
hive_web_access_guard_connections_per_ip: 100

# DDoS 緩和（OIDC / Nginx 側の補助制限：インスタンス全体）
hive_nginx_web_guard_requests_per_second: 200
hive_nginx_web_guard_request_burst: 400
hive_nginx_web_guard_connections: 1000
hive_nginx_web_guard_header_timeout_seconds: 30
hive_nginx_web_guard_body_timeout_seconds: 30
```

### 設定項目一覧

| 区分 | 変数名 | 既定値 (`all.yml`) | 説明 |
| --- | --- | --- | --- |
| 共通 | `hive_web_access_guard_interfaces` | `[eth0]` | 制限をかける外部インターフェース名の配列（必須） |
| 共通 | `hive_web_access_guard_ports` | `[80, 443]` | 制限をかける TCP ポート番号の配列（1〜15 個、必須） |
| 国別制限 | `hive_web_access_guard_country_enabled` | `false` | `true` で日本向け CIDR 以外からの新規接続を拒否 |
| 国別制限 | `hive_web_access_guard_ipv4_cidrs_file` | `/etc/hive/geoip/jp-ipv4.cidrs` | mother 環境上の日本向け IPv4 CIDR ファイルパス |
| 国別制限 | `hive_web_access_guard_ipv6_cidrs_file` | `/etc/hive/geoip/jp-ipv6.cidrs` | mother 環境上の日本向け IPv6 CIDR ファイルパス |
| 国別制限 | `hive_web_access_guard_ipv4_min_networks` | `1` | IPv4 CIDR の最小エントリ数（下回ると適用中止） |
| 国別制限 | `hive_web_access_guard_ipv6_min_networks` | `1` | IPv6 CIDR の最小エントリ数（下回ると適用中止） |
| 国別制限 | `hive_web_access_guard_min_update_ratio` | `0.8` | 前回適用数に対する最小比率（急減時に更新を拒否して前回設定を維持） |
| DDoS（ホスト） | `hive_web_access_guard_ddos_enabled` | `false` | `true` でホスト側接続制限と Nginx 補助制限を有効化 |
| DDoS（ホスト） | `hive_web_access_guard_new_connections_per_second` | `20` | 送信元 IP あたりの新規接続レート上限（件/秒） |
| DDoS（ホスト） | `hive_web_access_guard_new_connections_burst` | `40` | 新規接続レートのバースト許容数 |
| DDoS（ホスト） | `hive_web_access_guard_connections_per_ip` | `100` | 送信元 IP あたりの同時接続数上限 |
| DDoS（Nginx） | `hive_nginx_web_guard_requests_per_second` | `200` | Nginx インスタンス全体のリクエストレート上限（件/秒） |
| DDoS（Nginx） | `hive_nginx_web_guard_request_burst` | `400` | Nginx リクエストレートのバースト許容数 |
| DDoS（Nginx） | `hive_nginx_web_guard_connections` | `1000` | Nginx インスタンス全体の同時接続数上限 |
| DDoS（Nginx） | `hive_nginx_web_guard_header_timeout_seconds` | `30` | `client_header_timeout`（秒） |
| DDoS（Nginx） | `hive_nginx_web_guard_body_timeout_seconds` | `30` | `client_body_timeout`（秒） |

※ DDoS 緩和の数値は検証用の目安値です。共有 NAT 環境や WebSocket の利用状況に合わせて調整してください。Nginx 制限超過時は HTTP `429` を返します。

---

## 4. 反映コマンドの実行

mother 環境から、有効化・変更する内容に応じて以下の `hive` コマンドを実行します。

| 変更内容 | 実行するコマンド |
| --- | --- |
| **国別制限と DDoS 緩和の両方**、または **DDoS 緩和のみ** | `hive setup-hosts -T addon2` および `hive initialize-services -l oidc` |
| **国別制限のみ**（CIDR 更新を含む） | `hive setup-hosts -T addon2` のみ |

```sh
# 1. 各 hive ホストへ iptables / ip6tables / ipset ルールと起動時復元サービスを反映
hive setup-hosts -T addon2

# 2. OIDC コンテナ（Nginx）へ DDoS 補助制限を反映（DDoS 緩和を変更した場合に実行）
hive initialize-services -l oidc
```

### 反映時の挙動と注意点

- **再起動は不要**: ホストルール・systemd 復元サービス・Nginx 設定はいずれも即時反映されます。OS 再起動時は `hive-web-access-guard.service` が Docker 起動前にルールを復元します。
- **OIDC 初期化ロールの範囲**: `hive initialize-services -l oidc` は `oidc-init` だけでなく、`oidc` サービスに紐づく他ロール（`oidc-acme` 等）も合わせて実行します。
- **フェイルセーフ動作**:
  - **ホスト側**: IPv4/IPv6 の検証と新しいチェーン・ipset の準備がすべて成功してから切り替えます。初回導入時に CIDR が不正・欠落している場合は適用せず失敗します。更新時に検証で拒否された場合は、既存の適用済みデータ（`/var/lib/hive-web-access-guard/last-good.json`）を変更せず維持します。
  - **Nginx 側**: 一時ディレクトリでテンプレートを展開し `nginx -t` に合格してから反映・reload します。失敗時は稼働中の設定と次回起動用テンプレートを直前の状態に復元します。
- **複数ノードへの反映**: ノード単位で順次適用されるため、全ノード同時（原子的）な切り替えではありません。反映後は各ノードの結果を確認してください。

---

## 5. 反映後の確認

反映が完了したら、各 hive ホストおよびクライアントから動作を確認します。

### 1. ホスト側ルールの確認（各 hive ホストで実行）

```sh
# IPv4 / IPv6 の mangle テーブルを確認（PREROUTING から HWAG4_* / HWAG6_* へのジャンプとルール）
sudo iptables -t mangle -nvL
sudo ip6tables -t mangle -nvL

# 起動時復元サービスの状態を確認
sudo systemctl status hive-web-access-guard.service
```

### 2. Nginx 設定の確認（DDoS 緩和を有効にした場合、hive ホストで実行）

```sh
dexec oidc cat /etc/nginx/conf.d/hive-web-access-guard.conf
dexec oidc nginx -t
```

### 3. 疎通確認

既存接続は対象外のため、**新規接続**で確認してください。

- 日本国内の回線から対象 Web サイトへ正常にアクセスできること。
- 国別制限を有効にした場合、日本国外の環境（例: 海外リージョンの Codespaces 等）から対象ポートへ接続できないこと（タイムアウトし、`HWAG4_*` / `HWAG6_*` チェーンの DROP カウンターが増加すること）。

---

## 運用手順

### 国別 CIDR データの更新

1. mother 環境で新しい IPv4 / IPv6 CIDR ファイルを配置します（例: 「[2. 日本向け CIDR ファイルの準備](#2-日本向け-cidr-ファイルの準備国別制限を使う場合のみ)」のコマンドを再実行）。
2. mother 環境で `hive setup-hosts -T addon2` を実行して各 hive ホストへ反映します。

> データの定期取得や鮮度監視は運用側で行ってください。各ホストの `/var/lib/hive-web-access-guard/last-good.json` は最後に適用した内容の保存用であり、自動更新されません。

### 監視ポイント

- **ホスト側**: `iptables` / `ip6tables` の `mangle/PREROUTING` および `HWAG4_*` / `HWAG6_*` チェーンのパケットカウンター（DROP ごとの無制限カーネルログ出力は行いません）
- **Nginx 側**: HTTP `429` レスポンス数と Nginx エラーログ
- **データ整合性**: mother 環境上の CIDR ファイル更新日時と、各ノード間の `last-good.json` の一致

### 機能の無効化（通常の戻し方）

無効にしたい機能のフラグを `false` に戻し、有効化時と同じ `hive` コマンドを再実行します。片方だけの無効化も可能です。

- 国別制限を無効にする: `hive_web_access_guard_country_enabled: false` にして `hive setup-hosts -T addon2`
- DDoS 緩和を無効にする: `hive_web_access_guard_ddos_enabled: false` にして `hive setup-hosts -T addon2` と `hive initialize-services -l oidc`

両方を `false` にして反映すると、ホスト上の保護ルールは外れ、起動時復元サービスも保護ルールを復元しない状態になります。

### 手動による完全撤回（緊急時・関連ユニットごと削除する場合）

通常の無効化ではなく、起動時復元サービスや Docker ドロップインも含めて手動で撤回する場合は、コンソール経由の操作手段を確保し、設定の両フラグを `false` にしたうえで、各 hive ホストで以下を実行してください（Docker や firewall サービスへの影響は事前に確認してください）。

```sh
# 1. Docker 起動順序のドロップインを削除し、復元サービスを無効化・停止
sudo rm -f /etc/systemd/system/docker.service.d/web-access-guard.conf
sudo systemctl daemon-reload
sudo systemctl disable --now hive-web-access-guard.service

# 2. 適用中の iptables / ip6tables / ipset ルールを除去
sudo /usr/local/sbin/hive-web-access-guard --remove --state /var/lib/hive-web-access-guard/last-good.json

# 3. 今後の addon2 実行で再構成されないよう last-good.json を退避
sudo mv /var/lib/hive-web-access-guard/last-good.json /var/lib/hive-web-access-guard/last-good.json.bak
```
