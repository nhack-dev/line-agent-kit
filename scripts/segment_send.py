#!/usr/bin/env python3
"""タグで絞った友だちに1回だけ送る（セグメント配信）。既定は試し（何も送らない）。

  python3 scripts/segment_send.py --tag goal:time --message templates/messages/segment-example.json
  python3 scripts/segment_send.py --tag goal:time --exclude buyer:recipe-book --message ... --go

決まり:
  ・「配信停止（optout）」の人とブロックした人は Worker 側で必ず外れる
  ・送る前に今月の残り通数を確かめ、足りなければ送らない
  ・500人ずつ multicast。1回ごとに X-Line-Retry-Key を付けるので、やり直しても二重には届かない
  ・送ったら logs/segment-YYYYmmdd-HHMMSS.json に件数とステータスを残す（本文と userId は残さない）
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import datetime as dt
import json
import sys
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, http, line_base, load_env, mode_banner, need  # noqa: E402


def load_messages(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    msgs = data["messages"] if isinstance(data, dict) else data
    out = [{"type": "text", "text": m} if isinstance(m, str) else m for m in msgs]
    if not 1 <= len(out) <= 5:
        raise SystemExit("吹き出しは1〜5個にしてください")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", action="append", default=[], help="このタグを全部持つ人（何度でも）")
    ap.add_argument("--exclude", action="append", default=[], help="このタグを持つ人は外す（何度でも）")
    ap.add_argument("--message", required=True, help="送る中身の JSON（templates/messages/ を見本に）")
    ap.add_argument("--max", type=int, default=0, help="この人数を超えたら止める（0 は止めない）")
    ap.add_argument("--go", action="store_true", help="本当に送る")
    args = ap.parse_args()

    mode_banner(args.go)
    msgs = load_messages(Path(args.message))
    print(f"中身: 吹き出し {len(msgs)} 個")
    for m in msgs:
        print("  - " + (m.get("text", "")[:80].replace("\n", " ") if m.get("type") == "text" else f"[{m.get('type')}]"))

    env = load_env()
    need(env, "WORKER_URL", "ADMIN_TOKEN")
    q = urllib.parse.urlencode([("tag", t) for t in args.tag] + [("exclude", t) for t in args.exclude])
    st, aud = http("GET", f"{env['WORKER_URL'].rstrip('/')}/admin/audience?{q}", token=env["ADMIN_TOKEN"])
    if st != 200:
        raise SystemExit(f"対象の取得に失敗: {st} {aud}")
    ids = aud["user_ids"]
    print(f"対象: {len(ids)} 人（タグ {args.tag or '指定なし＝全員'}／外す {args.exclude + ['optout']}）")
    if not ids:
        print("対象 0 人なので終わります")
        return
    if args.max and len(ids) > args.max:
        raise SystemExit(f"--max {args.max} を超えたので止めました")

    need(env, "LINE_CHANNEL_ACCESS_TOKEN")
    tok = env["LINE_CHANNEL_ACCESS_TOKEN"]
    base = line_base(env)
    st, quota = http("GET", f"{base}/v2/bot/message/quota", token=tok)
    st2, used = http("GET", f"{base}/v2/bot/message/quota/consumption", token=tok)
    if st != 200 or st2 != 200:
        raise SystemExit(f"通数を確かめられないので止めました: {st} {quota} / {st2} {used}")
    if quota.get("type") == "limited":
        left = quota["value"] - used["totalUsage"]
        print(f"今月の残り: {left} 通（上限 {quota['value']}・使用 {used['totalUsage']}）→ 今回 {len(ids)} 通")
        if len(ids) > left:
            raise SystemExit("残りが足りないので送りません（対象を絞るか、プランを見直す）")

    if not args.go:
        print("試しなのでここまで。送るときは --go を付けてもう一度。")
        return

    results = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        key = str(uuid.uuid4())
        st, body = http("POST", f"{base}/v2/bot/message/multicast", token=tok,
                        body={"to": chunk, "messages": msgs}, headers={"X-Line-Retry-Key": key})
        print(f"  {i + 1}〜{i + len(chunk)} 人目: {st} {'' if st == 200 else body}")
        results.append({"from": i, "count": len(chunk), "status": st, "retry_key": key})
        if st not in (200, 409):   # 409 は同じキーがもう受け付けられている＝送り済み
            print("失敗したので残りは送りません。記録の from を見て、送れた人数を確かめてから続きを決める"
                  "（そのまま全員にやり直すと、送れた人に二重に届きます）")
            break
    logdir = ROOT / "logs"
    logdir.mkdir(exist_ok=True)
    out = logdir / f"segment-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"tags": args.tag, "exclude": args.exclude, "message_file": args.message,
                               "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"記録: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
