#!/usr/bin/env python3
"""LINE が送るのと同じ形の Webhook を、署名つきで Worker に送って動きを試す。

本物の LINE からは何も送られない。お客様の端末にも何も届かない（Worker が返事を LINE に出すかどうかは
Worker 側の LINE_API_BASE で決まる。手元の試しでは scripts/mock_line_api.py に向ける）。

  python3 scripts/send_test_event.py follow                       # 中身を見るだけ
  python3 scripts/send_test_event.py follow --go                  # 送る
  python3 scripts/send_test_event.py text --text アンケート --go
  python3 scripts/send_test_event.py postback --data "sv=first&q=goal&v=time" --go
  python3 scripts/send_test_event.py pick --datetime 2026-12-01T14:00 --go   # 予約の日時選択
  python3 scripts/send_test_event.py unfollow --go

  --url で送り先（既定は .env の WORKER_URL）。--user で架空の userId（既定 U0000…0001）。
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import http, load_env, mode_banner, need  # noqa: E402


def event(kind: str, user: str, args) -> dict:
    ev = {
        "type": kind, "mode": "active", "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user},
        "webhookEventId": "01TEST" + uuid.uuid4().hex[:20].upper(),
        "deliveryContext": {"isRedelivery": False},
    }
    if kind != "unfollow":
        ev["replyToken"] = uuid.uuid4().hex
    if kind == "follow":
        ev["follow"] = {"isUnblocked": False}
    if kind == "text":
        ev["type"] = "message"
        ev["message"] = {"type": "text", "id": "1", "text": args.text}
    if kind == "postback":
        ev["postback"] = {"data": args.data}
    if kind == "pick":
        ev["type"] = "postback"
        ev["postback"] = {"data": "book_pick", "params": {"datetime": args.datetime}}
    return ev


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["follow", "unfollow", "text", "postback", "pick"])
    ap.add_argument("--text", default="アンケート")
    ap.add_argument("--data", default="")
    ap.add_argument("--datetime", default="2026-12-01T14:00")
    ap.add_argument("--user", default="U" + "0" * 31 + "1")
    ap.add_argument("--url")
    ap.add_argument("--go", action="store_true")
    args = ap.parse_args()

    env = load_env()
    mode_banner(args.go)
    body = json.dumps({"destination": "Utest", "events": [event(args.kind, args.user, args)]},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    print(body.decode("utf-8"))
    if not args.go:
        return
    need(env, "LINE_CHANNEL_SECRET")
    url = (args.url or env.get("WORKER_URL", "")).rstrip("/") + "/webhook"
    sig = base64.b64encode(hmac.new(env["LINE_CHANNEL_SECRET"].encode(), body, hashlib.sha256).digest()).decode()
    st, res = http("POST", url, body=body, headers={"x-line-signature": sig})
    print(f"→ {url}: {st} {res}")
    if st != 200:
        sys.exit(1)


if __name__ == "__main__":
    main()
