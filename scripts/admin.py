#!/usr/bin/env python3
"""Worker の台帳を見る・直す（数字・タグ・シナリオ・予約）。

読むだけ（そのまま動く）:
  python3 scripts/admin.py stats
  python3 scripts/admin.py audience --tag goal:time --exclude buyer:recipe-book

書き換え（既定は試し・--go で実行）:
  python3 scripts/admin.py tag --ref 1a2b3c4d5e6f7a8b --add vip --remove new --go
  python3 scripts/admin.py enroll --ref 1a2b... --scenario welcome [--restart] --go
  python3 scripts/admin.py book --ref 1a2b... --at 2026-11-02T14:00 --title "オンライン相談" --url https://example.com/room --go
  python3 scripts/admin.py cancel --id bk_0123456789abcdef --go
  python3 scripts/admin.py run --go        # cron を待たずにステップとリマインドを1回動かす（試し用）

ref は友だちごとの札（購入リンクにも付く）。LINE の userId を知っているときは --user-id でもよい。
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import http, load_env, mode_banner, need  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    a = sub.add_parser("audience")
    a.add_argument("--tag", action="append", default=[])
    a.add_argument("--exclude", action="append", default=[])
    for name in ("tag", "enroll", "book"):
        p = sub.add_parser(name)
        p.add_argument("--ref")
        p.add_argument("--user-id")
        p.add_argument("--go", action="store_true")
        if name == "tag":
            p.add_argument("--add", action="append", default=[])
            p.add_argument("--remove", action="append", default=[])
        if name == "enroll":
            p.add_argument("--scenario", required=True)
            p.add_argument("--restart", action="store_true")
        if name == "book":
            p.add_argument("--at", required=True, help="現地時刻 2026-11-02T14:00")
            p.add_argument("--title")
            p.add_argument("--url")
    c = sub.add_parser("cancel")
    c.add_argument("--id", required=True)
    c.add_argument("--go", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--go", action="store_true")
    args = ap.parse_args()

    env = load_env()
    need(env, "WORKER_URL", "ADMIN_TOKEN")
    base = env["WORKER_URL"].rstrip("/")
    tok = env["ADMIN_TOKEN"]

    if args.cmd == "stats":
        st, body = http("GET", f"{base}/admin/stats", token=tok)
        print(st, json.dumps(body, ensure_ascii=False, indent=2))
        return
    if args.cmd == "audience":
        q = urllib.parse.urlencode([("tag", t) for t in args.tag] + [("exclude", t) for t in args.exclude])
        st, body = http("GET", f"{base}/admin/audience?{q}", token=tok)
        print(st, f"{body.get('count')} 人" if isinstance(body, dict) else body)
        return

    who = {}
    if getattr(args, "ref", None):
        who["ref"] = args.ref
    if getattr(args, "user_id", None):
        who["user_id"] = args.user_id
    if args.cmd in ("tag", "enroll", "book") and not who:
        raise SystemExit("--ref か --user-id が要ります")

    if args.cmd == "tag":
        path, body = "/admin/tags", {**who, "add": args.add, "remove": args.remove}
    elif args.cmd == "enroll":
        path, body = "/admin/enroll", {**who, "scenario_id": args.scenario, "restart": args.restart}
    elif args.cmd == "book":
        path, body = "/admin/bookings", {**who, "starts_at_local": args.at, "title": args.title, "url": args.url}
    elif args.cmd == "cancel":
        path, body = "/admin/bookings/cancel", {"id": args.id}
    else:
        path, body = "/admin/run", {}

    mode_banner(args.go)
    print(f"POST {path} {json.dumps(body, ensure_ascii=False)}")
    if not args.go:
        return
    st, res = http("POST", base + path, token=tok, body=body)
    print(st, json.dumps(res, ensure_ascii=False))
    if st != 200:
        sys.exit(1)


if __name__ == "__main__":
    main()
