// scripts/build_flow.py が作ったファイル。手で直さず config/flow.json を直す
export default {
  "name": "見本の流れ（架空の料理教室）",
  "timezone_offset_minutes": 540,
  "plan_monthly_free_messages": 200,
  "greeting": [
    "友だち追加ありがとうございます。\n「おうちごはん研究室」（架空）です。\n\nこれから1週間、15分で作れる晩ごはんのコツを少しずつお届けします。",
    "まず、いちばん気になることを教えてください。\n「アンケート」と送るか、下のメニューから選べます。\n\n配信を止めたいときは「配信停止」と送ってください。"
  ],
  "follow_tags": [
    "new"
  ],
  "optout": {
    "stop_words": [
      "配信停止"
    ],
    "restart_words": [
      "配信再開"
    ],
    "stop_reply": "配信を止めました。また受け取りたくなったら「配信再開」と送ってください。",
    "restart_reply": "配信を再開しました。"
  },
  "keywords": [
    {
      "id": "price",
      "match": "contains",
      "words": [
        "料金",
        "値段",
        "いくら"
      ],
      "reply": [
        "教材は 1,980円（税込）です。詳しくは「購入」と送ってください。"
      ],
      "add_tags": [
        "interest:price"
      ]
    },
    {
      "id": "faq",
      "match": "exact",
      "words": [
        "質問",
        "よくある質問"
      ],
      "reply": [
        "よくある質問はこちらです。\nhttps://example.com/faq"
      ]
    }
  ],
  "fallback_reply": [],
  "scenarios": [
    {
      "id": "welcome",
      "start": "follow",
      "stop_if_tags": [
        "buyer:recipe-book"
      ],
      "steps": [
        {
          "after_days": 1,
          "at": "19:00",
          "messages": [
            "【1日目】まな板を1枚にする段取りのコツ\n\n（ここに本文。600字くらいまでが読みやすい目安）"
          ]
        },
        {
          "after_days": 2,
          "at": "19:00",
          "messages": [
            "【2日目】味が決まらないときの「3つの調味料」\n\n（本文）"
          ]
        },
        {
          "after_days": 3,
          "at": "19:00",
          "only_if_tags": [
            "goal:time"
          ],
          "messages": [
            "【時短が気になる方へ】冷凍の使い分け\n\n（本文・アンケートで「時間」を選んだ方にだけ届く便）"
          ]
        },
        {
          "after_days": 4,
          "at": "19:00",
          "messages": [
            "【4日目】1週間の献立を10分で決める方法\n\n（本文）",
            {
              "type": "template",
              "altText": "レシピ本のご案内",
              "template": {
                "type": "buttons",
                "text": "30品のレシピ本（PDF）をご用意しました",
                "actions": [
                  {
                    "type": "postback",
                    "label": "詳しく見る",
                    "data": "buy=recipe-book"
                  }
                ]
              }
            }
          ]
        },
        {
          "after_days": 6,
          "at": "19:00",
          "messages": [
            "【最終日】ここまで読んでいただきありがとうございました。\nご質問は、このトークにそのまま送ってください。"
          ]
        }
      ]
    },
    {
      "id": "after-purchase",
      "start": "tag:buyer:recipe-book",
      "steps": [
        {
          "after_days": 3,
          "at": "12:00",
          "messages": [
            "レシピ本はお役に立っていますか？\n作ってみた料理があれば、ぜひ教えてください。"
          ]
        }
      ]
    }
  ],
  "surveys": [
    {
      "id": "first",
      "trigger_words": [
        "アンケート"
      ],
      "questions": [
        {
          "id": "goal",
          "text": "いちばん気になるのはどれですか？",
          "options": [
            {
              "label": "作る時間",
              "value": "time",
              "add_tags": [
                "goal:time"
              ]
            },
            {
              "label": "献立を決めること",
              "value": "menu",
              "add_tags": [
                "goal:menu"
              ]
            },
            {
              "label": "味つけ",
              "value": "taste",
              "add_tags": [
                "goal:taste"
              ]
            }
          ]
        },
        {
          "id": "family",
          "text": "何人分を作ることが多いですか？",
          "options": [
            {
              "label": "1人",
              "value": "1"
            },
            {
              "label": "2〜3人",
              "value": "2-3"
            },
            {
              "label": "4人以上",
              "value": "4+"
            }
          ]
        }
      ],
      "done_tags": [
        "survey:first"
      ],
      "done_reply": [
        "ご回答ありがとうございました。これからの配信の参考にします。"
      ]
    }
  ],
  "booking": {
    "trigger_words": [
      "予約",
      "相談"
    ],
    "title": "オンライン相談（30分）",
    "prompt": "ご希望の日時を選んでください（1日後〜30日後）",
    "min_days_ahead": 1,
    "max_days_ahead": 30,
    "url": "https://example.com/online-room",
    "add_tags": [
      "booked"
    ],
    "confirm_reply": [
      "{datetime} からの「{title}」で承りました。前日と1時間前にこのトークでお知らせします。"
    ],
    "reminders_minutes": [
      1440,
      60
    ],
    "reminder_messages": [
      "「{title}」は {datetime} からです。\n入り方：{url}"
    ]
  },
  "products": [
    {
      "id": "recipe-book",
      "name": "15分晩ごはん 30品レシピ本（PDF）",
      "payment_link_url": "https://buy.stripe.com/test_XXXXXXXXXXXX",
      "payment_link_id": "plink_XXXXXXXXXXXX",
      "buy_words": [
        "購入",
        "申し込み"
      ],
      "buy_reply": [
        "「{name}」はこちらからお申し込みいただけます（1,980円・税込）。\n{pay_url}\n\n販売者の表示：https://example.com/legal"
      ],
      "add_tags": [
        "buyer:recipe-book"
      ],
      "delivery": [
        "ご購入ありがとうございます。\n「{name}」はこちらからダウンロードできます。\nhttps://example.com/download/xxxx\n\n（リンクの期限やお問い合わせ先をここに書きます）"
      ]
    }
  ]
};
