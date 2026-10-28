# line-agent-kit

LINE公式アカウントの配信を、**あなたのAIエージェント（Claude Code など）が毎日回せる形**にしたキットです。
小さな Webhook サーバーを **Cloudflare Workers の無料プラン**に置き、流れの中身は `config/flow.json` 1枚に書きます。

## できること

| 機能 | 中身 | 通数に数えられるか |
|---|---|---|
| 友だち追加のあいさつ | 追加された瞬間に返す（最大5吹き出し） | 数えられない（reply） |
| ステップ配信 | 追加から「1日後の19:00」「30分後」など日数・時刻ごとの便。購入したら止まる | 数えられる（multicast） |
| タグ・属性 | アンケートの答え・押したボタン・キーワードでタグを付ける。タグで便を出し分ける | ― |
| キーワード自動応答 | 「料金」を含む／「質問」と完全一致 などで返す | 数えられない（reply） |
| リッチメニュー | トーク画面下のメニュー。押すとアンケート・予約・購入・タグ付けにつながる | ― |
| セグメント配信 | 「goal:time を持ち、buyer を持たない人」だけに1回送る | 数えられる |
| 予約とリマインド | LINE の日時選択で予約 → 前日・1時間前などに自動で知らせる | 予約の返事は数えられない／リマインドは数えられる |
| アンケート | ボタン（クイックリプライ）で1問ずつ。答えは保存し、タグにもなる | 数えられない（reply） |
| 決済後の自動お届け（任意） | Stripe の支払いが終わったら、その人の LINE に教材のお届けを1通 | 数えられる |
| 配信停止 | 「配信停止」で止まり「配信再開」で戻る。止めた人には何も送らない | 数えられない（reply） |

お客様のメッセージ本文は保存しません。保存するのは「誰が・いつ・どのタグ・どの段にいるか」だけです。

## 費用（あなたの側だけ・2026年10月に公式で確かめた値）

- **LINE公式アカウント**（日本・税別）… コミュニケーション 0円／月200通、ライト 5,000円／月5,000通、スタンダード 15,000円／月30,000通。
  追加で送れるのはスタンダードだけ（20万通／月まで1通3円・それを超えた分は1通2.5円・2026-10-01 改定）。
  reply（あいさつ・キーワード・アンケートの返事）は数えられません。数えられるのは push・multicast・broadcast・narrowcast で、**送った人数**で数えます。
  出どころ: https://www.lycbiz.com/jp/service/line-official-account/plan/ ・ https://developers.line.biz/en/docs/messaging-api/pricing/
- **Cloudflare Workers 無料プラン** … 1日10万リクエスト・1回の処理で CPU 10ミリ秒・cron は1アカウント5本まで（このキットは1本）。
  D1（台帳）無料枠は 1日に読み500万行・書き10万行・保存5GB。
  出どころ: https://developers.cloudflare.com/workers/platform/limits/ ・ https://developers.cloudflare.com/d1/platform/pricing/
- **Stripe**（使うときだけ）… 日本のカード決済 3.6%。Payment Links 自体の追加料金・月額はなし。出どころ: https://stripe.com/jp/pricing

このキットの作り手のサーバー・鍵・課金は一切使いません。鍵はあなたの `.env` と Cloudflare の secret にだけ置きます。

## 最初の10分（本物の LINE を使わず、手元で全部の動きを見る）

要るもの: Python 3.11 以上、Node.js 18 以上（`npx` が使えること）。

```bash
cp .env.example .env
# .env を次の値にする（試し用。本物の鍵ではない）
#   LINE_CHANNEL_ACCESS_TOKEN=test-token
#   LINE_CHANNEL_SECRET=test-secret
#   WORKER_URL=http://127.0.0.1:8787
#   ADMIN_TOKEN=test-admin
#   LINE_API_BASE=http://127.0.0.1:8790
#   LINE_DATA_API_BASE=http://127.0.0.1:8790

python3 scripts/build_flow.py --write          # 見本の流れを Worker に入れる
printf 'LINE_CHANNEL_ACCESS_TOKEN=test-token\nLINE_CHANNEL_SECRET=test-secret\nADMIN_TOKEN=test-admin\nLINE_API_BASE=http://127.0.0.1:8790\n' > worker/.dev.vars

cd worker
npm install                                   # wrangler を入れる（初回だけ・1〜2分）
npx wrangler d1 execute line-agent-kit --local --file=schema.sql
cd ..

# 窓を2つ使う
python3 scripts/mock_line_api.py                # 窓1：にせ LINE（送ろうとした中身が見える）
cd worker && npm run dev                        # 窓2：Worker（http://127.0.0.1:8787）

# 窓3で、LINE と同じ形の出来事を送ってみる
python3 scripts/send_test_event.py follow --go
python3 scripts/send_test_event.py text --text アンケート --go
python3 scripts/send_test_event.py postback --data "sv=first&q=goal&v=time" --go
python3 scripts/admin.py stats
```

窓1に、あいさつ・アンケートの質問が「送ろうとした中身」として出れば動いています。

## 本番に出す（30〜60分）

順番どおりの細かい手順は [playbooks/01-setup.md](playbooks/01-setup.md)。あらすじは次のとおりです。

1. **LINE公式アカウントを作る**（LINE Official Account Manager）→ 設定 → Messaging API を「利用する」
2. **LINE Developers** でチャネルシークレットと、チャネルアクセストークン（長期）を出す
3. **Cloudflare** のアカウントを作り、`npx wrangler login`
4. `npx wrangler d1 create line-agent-kit` → 出た `database_id` を `worker/wrangler.toml` に入れる → `schema.sql` を `--remote` で流す
5. `npx wrangler secret put LINE_CHANNEL_ACCESS_TOKEN`（ほか `LINE_CHANNEL_SECRET`・`ADMIN_TOKEN`）
6. `config/flow.example.json` を `config/flow.json` にコピーして自分の中身に書き換え → `python3 scripts/build_flow.py --write` → `npx wrangler deploy`
7. LINE Developers の Webhook URL に `https://<Worker のURL>/webhook` を入れ「Webhookの利用」をオン → 検証
8. LINE Official Account Manager の応答設定で **「応答メッセージ」と「あいさつメッセージ」をオフ**（オンのままだと、このキットの返事と二重になる）
9. `python3 scripts/check_setup.py --online` → 自分のスマホで友だち追加して、あいさつが届くか見る

## あなたが取るキー

| キー | 取る場所 | 使う所 |
|---|---|---|
| チャネルシークレット | LINE Developers → チャネル → チャネル基本設定 | Webhook の署名の確かめ |
| チャネルアクセストークン（長期） | LINE Developers → チャネル → Messaging API設定 | 送る・メニューを作る |
| Cloudflare のアカウント | https://dash.cloudflare.com/ （`npx wrangler login` でつなぐ） | Worker と台帳を置く |
| ADMIN_TOKEN | 自分で作る `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | scripts/ から台帳を読む・直す |
| Stripe の Webhook 署名シークレット（任意） | Stripe → 開発者 → Webhook → エンドポイント | 決済後の自動お届け |

## できないこと・気をつけること（正直に）

- **無料プラン（コミュニケーション）とライトは、上限を超えると送れません**（追加購入ができるのはスタンダードだけ）。`build_flow.py --friends` で月の見積もりを先に出してください。
- **ステップ配信は全員に同じ文**です（まとめ送り＝multicast のため、名前などの差し込みはできません）。人ごとに変えたいものは、ボタン → reply（無料）で返す形にしています（購入リンクがその例）。
- **narrowcast（LINE 側で属性を絞る配信）は使っていません**。公式の決まりで、属性で絞るには対象100人以上・最終の受け手50人以上が要り、小さなアカウントでは使えないためです。代わりに台帳のタグで絞って multicast（500人ずつ）します。
- **Webhook を入れる前からいた友だち**は、その人が何か送るかメニューを押すまで台帳に入りません。
- **予約は「選んだ日時を受け取る」だけ**です。枠の数・重なり・担当者のカレンダーは見ません。本格的な予約は予約用のサービスで受け、`scripts/admin.py book` でリマインドだけ登録する形を使ってください。
- **グループ・複数人トークの出来事は無視**します（1対1のトークだけ）。
- 無料の Workers は1回の処理で外への通信が50回までです。cron 1回で送るのは multicast 30回（＝最大15,000人）まで。残りは5分後の次の回に送ります。
- お届けのリンク（`delivery`）は、知っていれば誰でも開けるリンクにしないでください（期限つきのリンク・会員ページを推奨）。

## 中身

```
README.md              この紙
AGENT.md               エージェントへの指示書（毎日やること・判断の基準・やってはいけないこと）
CLAUDE.md              Claude Code 用（AGENT.md を読む）
config/flow.example.json  流れの見本（架空の料理教室）
worker/                Cloudflare Worker（src/index.js・schema.sql・wrangler.toml）
scripts/               Python 3.11 標準ライブラリだけ。送るものは --go のときだけ送る
  build_flow.py        flow.json を確かめて Worker に書き出す・通数を見積もる
  check_setup.py       用意ができているか（--online で LINE と Worker に問い合わせ・読むだけ）
  admin.py             数字・タグ・シナリオ・予約を見る／直す
  segment_send.py      タグで絞って1回送る（残り通数を先に確かめる）
  richmenu.py          リッチメニューを作る（仮の画像も作れる）
  send_test_event.py   LINE と同じ形の出来事を署名つきで送って試す
  mock_line_api.py     手元の試し用のにせ LINE API
playbooks/             作業ごとの手順
templates/             リッチメニュー・メッセージの型
docs/                  仕様と出どころ
LICENSE
```


---

## このキットは N-Hack のAIエージェント専用です

このキットは N-Hack の受講生さん専用のプレゼントです。**N-Hack のAIエージェント
（N-Hack のプラグインを入れた Claude Code など）が、このパソコンで動いていること**を
前提にしています。

- どのスクリプトも、最初に `scripts/nhack_gate.py`（門）を通ります。門は、このパソコンに
  N-Hack のAIエージェントの「印」があるかを**読むだけ**で確かめます（ネットにつなぎません・
  何も書き換えません・プラグインには一切触れません）。
- 印が足りない環境では、スクリプトは動かずに止まります（終了コード 2）。この環境でだけ
  動くのが正しい姿です。
- いま N-Hack 環境かどうかは、次のコマンドで確かめられます。

```bash
python3 scripts/nhack_gate.py
```

N-Hack 以外のパソコンにコピーしても動きません。受講生ページ・コンサルチャンネルの案内に
沿ってご利用ください。


---

## 困ったとき・もっと伸ばしたいとき

分からない・動かない・時間がかかっている——そんなときは、ひとりで抱えないでください。
**N-Hack の受講生ページ／個別コンサルチャンネル**から、担当にそのまま相談できます。
あなた専用のAIと伴走しながら、最短で結果まで一緒に持っていきます。

このキットのAIは、あなたが詰まったときや区切りのときに、自分から相談先を案内します。
