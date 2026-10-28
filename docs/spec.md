# 仕様（flow.json・ボタンの決まり・台帳）

## config/flow.json

見本は `config/flow.example.json`。直したら必ず `python3 scripts/build_flow.py --write` → deploy。

| 項目 | 中身 |
|---|---|
| `timezone_offset_minutes` | 時刻の基準。日本は 540（UTC+9） |
| `plan_monthly_free_messages` | 通数の見積もりで比べる枠（コミュニケーション 200・ライト 5000・スタンダード 30000） |
| `greeting` | 友だち追加のあいさつ。最大5吹き出し |
| `follow_tags` | 友だち追加で付けるタグ |
| `optout` | 配信停止・再開の言葉と返事。停止すると `optout` タグが付き、全シナリオが止まる |
| `keywords[]` | `id`・`match`（`exact`＝完全一致／`contains`＝含む）・`words`・`reply`・`add_tags` |
| `fallback_reply` | どれにも当たらないときの返事。空なら黙る（おすすめは空） |
| `scenarios[]` | ステップ配信。下の表 |
| `surveys[]` | アンケート。`trigger_words` か postback `survey=<id>` で始まる |
| `booking` | 予約とリマインド |
| `products[]` | 購入リンクと、決済後のお届け |

### メッセージの書き方

- 文字列 … そのままテキストの吹き出しになる（5,000字まで）
- オブジェクト … LINE のメッセージオブジェクトをそのまま（Flex・テンプレート・画像など）。型は `templates/messages/`
- 差し込み … reply で返すもの（キーワード・購入・予約の返事・お届け）だけ `{pay_url}` `{name}` `{datetime}` `{title}` `{url}` が使える。**ステップの便には使えない**（`build_flow.py` が止める）

### scenarios（ステップ配信）

| 項目 | 中身 |
|---|---|
| `id` | 名前（英数字） |
| `start` | `follow`（友だち追加で開始）／`tag:<タグ>`（そのタグが付いたら開始）／`manual`（`admin.py enroll` だけ） |
| `stop_if_tags` | このタグが付いたら止める（例 購入した人に売り込みを続けない） |
| `steps[]` | 上から順に。`after_days`＋`at`（開始日から N 日後のその時刻）か `after_minutes`（開始から M 分後） |
| `steps[].only_if_tags` | このタグのどれかを持つ人にだけ送る。持たない人はその便を飛ばす |

- 同じ人は同じシナリオに2回入らない（やり直しは `admin.py enroll --restart`）
- 当日の時刻を過ぎてから入った人の `after_days: 0` の便は、次の cron（最大5分後）で送る
- ブロック・配信停止の人の便は送らずに止める

## ボタン（postback）の data の決まり

リッチメニュー・テンプレート・Flex のボタンの `data` に書く。

| data | 動き |
|---|---|
| `kw=<keywords の id>` | そのキーワードの返事を返す |
| `tag=<タグ>` | タグを付ける（ほかと `&` でつなげる。例 `tag=interest:menu&kw=price`） |
| `survey=<surveys の id>` | アンケートを始める |
| `sv=<id>&q=<問い>&v=<答え>` | アンケートの答え（Worker が自動で作る） |
| `buy=<products の id>` | その人の札つきの購入リンクを返す（reply・無料） |
| `book` | 予約の日時選択を出す |
| `book_pick` | 日時選択の結果（Worker が使う） |

## 台帳（D1 の表）

`worker/schema.sql` に全部ある。お客様のメッセージ本文は保存しない。

| 表 | 中身 |
|---|---|
| friends | userId・札（ref）・状態（active／blocked） |
| tags | 人ごとのタグ |
| enrollments | シナリオごとの「次の便」と時刻 |
| answers | アンケートの答え |
| bookings | 予約とリマインドの送り済み |
| seen_events | 同じ Webhook を2回処理しないための控え（7日で消す） |
| send_log | 送った記録（種類・人数・LINE のステータス。本文なし） |
| purchases | 決済の記録（Stripe の event id・商品・金額） |

`ref` は外に出してよい札です（購入リンクに付く）。LINE の userId はリンクに出しません。

## 管理用の入口（ADMIN_TOKEN が要る）

| 入口 | 道具 |
|---|---|
| GET `/admin/stats` | `admin.py stats` |
| GET `/admin/audience?tag=..&exclude=..` | `admin.py audience`・`segment_send.py`（optout は必ず外れる） |
| POST `/admin/tags` | `admin.py tag` |
| POST `/admin/enroll` | `admin.py enroll` |
| POST `/admin/bookings`・`/admin/bookings/cancel` | `admin.py book`・`cancel` |
| POST `/admin/run` | `admin.py run`（cron を待たずに1回動かす・試し用） |

## 公式の仕様で確かめたこと（2026年10月）

- Webhook の署名は `x-line-signature` ヘッダー。チャネルシークレットで本文の HMAC-SHA256 を取り Base64 にした値と比べる
- 同じ出来事が2回届くことがある → `webhookEventId` で1回だけ処理する
- reply トークンは1回だけ・受け取ってから1分以内
- push・multicast は1回に5吹き出しまで。multicast は1回500人まで。`X-Line-Retry-Key`（UUID）で二重送信を防げる（同じキーは409）
- リッチメニュー画像は JPEG／PNG・幅800〜2500px・高さ250px以上・幅÷高さ1.45以上・1MBまで。上げ直しはできない（作り直す）
- 出どころ: https://developers.line.biz/en/reference/messaging-api/ ・ https://developers.line.biz/en/docs/messaging-api/receiving-messages/
