#!/usr/bin/env python3
"""用意ができているかを確かめる（読むだけ・何も送らない）。

  python3 scripts/check_setup.py            # .env と手元のファイルだけ見る
  python3 scripts/check_setup.py --online   # LINE と Worker にも問い合わせる（読むだけ）

--online で見るもの:
  ・LINE: ボットの情報（GET /v2/bot/info）・今月の上限（/v2/bot/message/quota）・今月の使用数（/quota/consumption）
  ・LINE: Webhook の設定（GET /v2/bot/channel/webhook/endpoint）
  ・Worker: /health と /admin/stats
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, http, line_base, load_env  # noqa: E402

REQUIRED = ["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET", "WORKER_URL", "ADMIN_TOKEN"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true")
    args = ap.parse_args()

    env = load_env()
    ok = True
    print("1) .env")
    if not (ROOT / ".env").exists():
        print("   .env がありません → cp .env.example .env して値を入れてください")
    for k in REQUIRED:
        state = "あり" if env.get(k) else "なし"
        ok &= bool(env.get(k))
        print(f"   {k}: {state}")
    print(f"   STRIPE_WEBHOOK_SECRET: {'あり' if env.get('STRIPE_WEBHOOK_SECRET') else 'なし（決済を使わないなら不要）'}")

    print("2) 手元のファイル")
    flow = ROOT / "config" / "flow.json"
    gen = ROOT / "worker" / "src" / "flow.generated.js"
    print(f"   config/flow.json: {'あり' if flow.exists() else 'なし（見本 config/flow.example.json をコピーして作る）'}")
    print(f"   worker/src/flow.generated.js: {'あり' if gen.exists() else 'なし（python3 scripts/build_flow.py --write）'}")
    if flow.exists() and gen.exists() and flow.stat().st_mtime > gen.stat().st_mtime:
        print("   注意: flow.json の方が新しいです → build_flow.py --write してから deploy")
    wt = ROOT / "worker" / "wrangler.toml"
    if wt.exists() and "REPLACE_WITH" in wt.read_text(encoding="utf-8"):
        print("   注意: worker/wrangler.toml の database_id が見本のままです")

    if not args.online:
        print("（LINE と Worker への問い合わせは --online）")
        sys.exit(0 if ok else 1)

    if not ok:
        print("足りない値があるので問い合わせは止めます")
        sys.exit(1)
    tok = env["LINE_CHANNEL_ACCESS_TOKEN"]
    base = line_base(env)
    print("3) LINE")
    st, info = http("GET", f"{base}/v2/bot/info", token=tok)
    print(f"   ボット: {st} {info.get('displayName', '') if isinstance(info, dict) else info}")
    st, q = http("GET", f"{base}/v2/bot/message/quota", token=tok)
    st2, c = http("GET", f"{base}/v2/bot/message/quota/consumption", token=tok)
    if st == 200 and st2 == 200:
        limit = q.get("value") if q.get("type") == "limited" else "上限なし"
        print(f"   今月の通数: 使用 {c.get('totalUsage')} ／ 上限 {limit}（使用数は目安の値）")
    else:
        print(f"   通数の取得に失敗: {st} {q} / {st2} {c}")
    st, wh = http("GET", f"{base}/v2/bot/channel/webhook/endpoint", token=tok)
    if st == 200:
        print(f"   Webhook: {wh.get('endpoint')}（利用 {'オン' if wh.get('active') else 'オフ'}）")
        if wh.get("endpoint") != env["WORKER_URL"].rstrip("/") + "/webhook":
            print(f"   注意: WORKER_URL/webhook と一致しません（LINE Developers の Messaging API 設定で直す）")

    print("4) Worker")
    st, h = http("GET", env["WORKER_URL"].rstrip("/") + "/health")
    print(f"   /health: {st} {h}")
    st, s = http("GET", env["WORKER_URL"].rstrip("/") + "/admin/stats", token=env["ADMIN_TOKEN"])
    print(f"   /admin/stats: {st} {s}")


if __name__ == "__main__":
    main()
