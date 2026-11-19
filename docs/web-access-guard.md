# Web アクセス制限

この機能は既定で無効です。本リポジトリには国別データを含めません。GeoIP データの提供元、利用条件、国判定基準、更新方法は運用者が決定する必要があります。

Swarm ingress は Nginx 到着前に送信元を変更するため、Nginx GeoIP2 のみでは元の IP を判定できません。ホストの mangle PREROUTING で公開 TCP ポートへの新規接続を ipset と照合し、ipset にない IP を拒否します。日本と判定した CIDR は IPv4/IPv6 両方必要です。既存接続は対象外です。Nginx の制限は送信元ごとではなくインスタンス全体に適用します。

国情報には誤判定があり、VPN やプロキシ越しの実際の所在地を保証できません。回線飽和や大規模分散攻撃はこの構成だけでは防げません。

## 有効化前の確認

実際に Web を公開する全ポートを列挙します。現行 inventory の候補は 80、443 です。サービス・ステージ・セキュリティグループごとに実際の公開状態と用途を確認します。この実装は TCP のみです。HTTP/3 等の UDP Web 公開がある場合は保護対象にならないため、有効化前に別途対応が必要です。DNS や Socket Warp の UDP ポートは対象に含めません。

## 設定

`inventory/group_vars/all.yml` に全ステージ共通の設定項目を置いています。両機能は既定で無効です。`hive_web_access_guard_country_enabled` は日本向け CIDR による制限、`hive_web_access_guard_ddos_enabled` はホストの接続制限と Nginx の補助制限を切り替えます。どちらか片方だけでも有効にできます。DDoS 緩和だけの場合、CIDR ファイルの配置や `ipset` のインストールは不要です。

一時適用試験で確認した設定（ホスト側の対象は TCP 80/443。直接公開ポートも制限する場合は対象ポートに追加してください）:

```yaml
hive_web_access_guard_interfaces: [eth0]
hive_web_access_guard_ports: [80, 443]

hive_web_access_guard_country_enabled: true
hive_web_access_guard_ipv4_cidrs_file: /etc/hive/geoip/jp-ipv4.cidrs
hive_web_access_guard_ipv6_cidrs_file: /etc/hive/geoip/jp-ipv6.cidrs
hive_web_access_guard_ipv4_min_networks: 1
hive_web_access_guard_ipv6_min_networks: 1
hive_web_access_guard_min_update_ratio: 0.8

hive_web_access_guard_ddos_enabled: true
hive_web_access_guard_new_connections_per_second: 20
hive_web_access_guard_new_connections_burst: 40
hive_web_access_guard_connections_per_ip: 100

hive_nginx_web_guard_requests_per_second: 200
hive_nginx_web_guard_request_burst: 400
hive_nginx_web_guard_connections: 1000
hive_nginx_web_guard_header_timeout_seconds: 30
hive_nginx_web_guard_body_timeout_seconds: 30
```

### IPdeny の日本向け CIDR ファイルを取得する

国別制限を有効にする場合は、`hive` コマンドを実行する **mother 環境**（Codespaces を利用している場合は開発コンテナ内）で以下を実行します。ファイルは hive サーバーではなく mother 環境に配置します。両方のダウンロードが完了してから、設定例のパスに配置します。

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

取得・配置だけでは制限は有効になりません。[IPdeny の利用条件](https://www.ipdeny.com/tos.php)を確認し、反映手順に進んでください。

## 反映手順

国別制限を有効にする場合のみ、mother 環境に日本向け CIDR ファイルを両方配置します。

```sh
hive setup-hosts -T addon2
hive initialize-services -l oidc
```

`addon2` がホストルールを反映します。国別制限だけを変更する場合はこのコマンドで足ります。DDoS 緩和を変更する場合は OIDC の `initialize-services` も実行し、Nginx の設定を反映します。無効化も同じ手順です。両方を無効化するとホストルールを外し、既存の復元サービスは保護ルールを復元しない設定になります。追加の反映コマンドや再起動は不要です。反映後は各ノードの IPv4/IPv6 ルールと、有効にした機能の動作を新規接続で確認します。

IP セットは検証済み候補から作り直し、全ファミリーの準備後に新旧ルールを切り替えます。初期導入時にデータがない場合は何も保護せず失敗します。既存データの更新時に拒否された候補は last-good を変更しません。データ更新は、検証した CIDR ファイルを用意して対象ステージの addon2 を再実行します。更新元の取得と期限監視は運用側の責任です。複数ノードの一括切り替えは原子的ではなく、ノードごとに結果を確認してください。

Nginx は候補テンプレートから設定を生成し `nginx -t` を通してから反映・reload します。失敗時には稼働中の設定と次回起動用テンプレートを復元します。Nginx 制限を無効化する場合も `oidc-init` を再実行して反映します。

## 監視・撤回

iptables の `mangle/PREROUTING` と `HWAG4_` / `HWAG6_` チェーンのカウンター、Nginx の 429 とエラーログ、CIDR の更新時刻、ノード間の last-good を監視します。DROP ごとの無制限ログ出力は行いません。`/var/lib/hive-web-access-guard/last-good.json` は適用済みデータであり、取得元の最新性を保証するものではありません。

通常は対象の有効化フラグを `false` にして再適用します。手動で完全撤回する場合は、コンソール経由の操作を確保し、両フラグを `false` にしてから、各ホストの Docker ドロップイン `/etc/systemd/system/docker.service.d/web-access-guard.conf` を除去して `systemctl daemon-reload`、guard サービスを無効化・停止し、次のコマンドを実行します。Docker や firewall サービスへの影響は事前に検証してください。以後の `addon2` で再構成しないよう、撤回後は `last-good.json` を別のパスへ退避してください。

```sh
/usr/local/sbin/hive-web-access-guard --remove --state /var/lib/hive-web-access-guard/last-good.json
```
