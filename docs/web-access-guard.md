# Web アクセス制限（検証用）

この機能は既定で無効です。**Swarm ingress の実経路、IPv4/IPv6、再起動と復旧を検証するまでは本番で有効化しないでください。** 本リポジトリには国別データを含めません。GeoIP データの提供元、利用条件、国判定基準、更新方法は運用者が決定する必要があります。

Swarm ingress は Nginx 到着前に送信元を変更するため、Nginx GeoIP2 のみでは元の IP を判定できません。ホストの mangle PREROUTING で公開 TCP ポートへの新規接続を ipset と照合し、ipset にない IP を拒否します。日本と判定した CIDR は IPv4/IPv6 両方必要です。既存接続は対象外です。Nginx の制限は送信元ごとではなくインスタンス全体に適用します。

国情報には誤判定があり、VPN やプロキシ越しの実際の所在地を保証できません。回線飽和や大規模分散攻撃はこの構成だけでは防げません。

## 有効化前の確認

- 実際に Web を公開する全ポートを列挙します。現行 inventory の候補は 80、443、Keycloak 18081、IDM gateway 10443、SCEP 13000 です。サービス・ステージ・セキュリティグループごとに実際の公開状態と用途を確認します。この実装は TCP のみです。HTTP/3 等の UDP Web 公開がある場合は保護対象にならないため、有効化前に別途対応が必要です。DNS や Socket Warp の UDP ポートは対象に含めません。
- 各 hive で対象の外部インターフェースを指定します。指定したインターフェースに届き、宛先がローカルな対象ポートだけを制御します。前段で送信元が変換される場合は利用できません。内部通信が同一インターフェース・ポートを通る場合も影響を評価してください。
- IPv4/IPv6 双方の CIDR ファイルを Ansible コントローラー上に用意します。1 行 1 CIDR、空行と `#` コメントを許可します。提供元のライセンスと日本の定義、データ更新時刻と IPv6 の対応状況を確認し、古いデータや不明な国を許可しない運用を決めます。未知の IP は新規接続を拒否します。国外の例外は設けません。
- ホストの `iptables.service` と `ip6tables.service` はあらかじめ稼働している必要があります。ロールは停止中のサービスを開始せずエラーにします。iptables の再起動やルールの外部変更が Docker のルールや guard の復元に及ぼす影響を実機相当の環境で確認してください。
- 初回は両方のデータと設定を検証してからチェーンを接続します。更新失敗時は既存ルールと last-good を維持します。CIDR 数の下限・更新時の減少比率は、採用するデータの実態に合わせて設定します。デフォルトの下限 `1` はデータの正確性・網羅性を保証しません。
- 新規接続の頻度・同時接続数の初期値は仮値です。共有 NAT、WebSocket、アップロード、ログイン処理を含む負荷試験で調整します。必要な監視、誤検知時の対応、緊急コンソール経由の復旧を事前に用意します。

## 設定

検証環境で明示的に指定する変数:

```yaml
hive_web_access_guard_enabled: true
hive_web_access_guard_interfaces: [eth0]
hive_web_access_guard_ports: [80, 443, 10443, 13000, 18081]
hive_web_access_guard_ipv4_cidrs_file: /path/on/controller/jp-ipv4.cidrs
hive_web_access_guard_ipv6_cidrs_file: /path/on/controller/jp-ipv6.cidrs
hive_web_access_guard_ipv4_min_networks: 1
hive_web_access_guard_ipv6_min_networks: 1
hive_web_access_guard_min_update_ratio: 0.8
hive_web_access_guard_new_connections_per_second: 20
hive_web_access_guard_new_connections_burst: 40
hive_web_access_guard_connections_per_ip: 100

hive_nginx_web_guard_enabled: true
hive_nginx_web_guard_requests_per_second: 200
hive_nginx_web_guard_request_burst: 400
hive_nginx_web_guard_connections: 1000
hive_nginx_web_guard_header_timeout_seconds: 30
hive_nginx_web_guard_body_timeout_seconds: 30
```

IP セットは検証済み候補から作り直し、全ファミリーの準備後に新旧ルールを切り替えます。初期導入時にデータがない場合は何も保護せず失敗します。既存データの更新時に拒否された候補は last-good を変更しません。データ更新は、検証した CIDR ファイルを用意して対象ステージの addon2 を再実行します。更新元の取得と期限監視は運用側の責任です。複数ノードの一括切り替えは原子的ではなく、ノードごとに結果を確認してください。

Nginx は候補テンプレートから設定を生成し `nginx -t` を通してから反映・reload します。失敗時には稼働中の設定と次回起動用テンプレートを復元します。Nginx 制限を無効化する場合も `oidc-init` を再実行して反映します。

## 監視・撤回

iptables の `mangle/PREROUTING` と `HWAG4_` / `HWAG6_` チェーンのカウンター、Nginx の 429 とエラーログ、CIDR の更新時刻、ノード間の last-good を監視します。DROP ごとの無制限ログ出力は行いません。`/var/lib/hive-web-access-guard/last-good.json` は適用済みデータであり、取得元の最新性を保証するものではありません。

撤回は国外からのアクセスを再び可能にするため、許可を得た保守時に行います。コンソール経由の操作を確保し、再適用を防ぐため有効化設定を取り除いてから、各ホストの Docker ドロップイン `/etc/systemd/system/docker.service.d/web-access-guard.conf` を除去して `systemctl daemon-reload`、guard サービスを無効化・停止し、次のコマンドを実行します。Docker や firewall サービスへの影響は事前に検証してください。last-good は自動削除しません。

```sh
/usr/local/sbin/hive-web-access-guard --remove --state /var/lib/hive-web-access-guard/last-good.json
```
