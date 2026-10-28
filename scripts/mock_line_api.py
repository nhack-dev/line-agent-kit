#!/usr/bin/env python3
"""手元の試し用の「にせ LINE API」。届いた送信をそのまま画面とファイルに出し、本物には何も送らない。

  python3 scripts/mock_line_api.py --port 8790
  → worker/.dev.vars に LINE_API_BASE=http://127.0.0.1:8790 と書いて `npx wrangler dev` すると、
    Worker が送ろうとした reply / push / multicast が logs/mock-line.jsonl に1行ずつ残る。
  → .env にも LINE_API_BASE=http://127.0.0.1:8790 と書けば scripts/ も同じにせ物を相手にする。

答える場所: reply / push / multicast / broadcast（200）・quota（上限 200）・quota/consumption・bot/info・
richmenu 作成（ID を返す）・richmenu 画像・既定のリッチメニュー・webhook endpoint。
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

LOG = ROOT / "logs" / "mock-line.jsonl"
STATE = {"sent": 0}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, obj: dict) -> None:
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):  # 標準の出力は使わない
        pass

    def _record(self, body) -> None:
        LOG.parent.mkdir(exist_ok=True)
        row = {"t": time.strftime("%H:%M:%S"), "method": self.command, "path": self.path,
               "retry_key": self.headers.get("X-Line-Retry-Key"), "body": body}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False)[:400])

    def do_GET(self):
        self._record(None)
        p = self.path
        if p.endswith("/message/quota"):
            return self._reply(200, {"type": "limited", "value": 200})
        if p.endswith("/quota/consumption"):
            return self._reply(200, {"totalUsage": STATE["sent"]})
        if p.endswith("/bot/info"):
            return self._reply(200, {"displayName": "にせ LINE（試し）", "userId": "Umock"})
        if p.endswith("/webhook/endpoint"):
            return self._reply(200, {"endpoint": "http://127.0.0.1:8787/webhook", "active": True})
        if p.endswith("/richmenu/list"):
            return self._reply(200, {"richmenus": []})
        if p.endswith("/user/all/richmenu"):
            return self._reply(404, {"message": "no default"})
        return self._reply(404, {"message": "mock: not found"})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw) if raw else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = f"<{len(raw)} bytes>"
        self._record(body)
        p = self.path
        if p.endswith("/message/push"):
            STATE["sent"] += 1
        elif p.endswith("/message/multicast"):
            STATE["sent"] += len(body.get("to", []))
        if p.endswith("/v2/bot/richmenu"):
            return self._reply(200, {"richMenuId": "richmenu-mock0001"})
        return self._reply(200, {})

    def do_DELETE(self):
        self._record(None)
        return self._reply(200, {})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    print(f"にせ LINE API: http://127.0.0.1:{args.port}（止めるときは Ctrl+C）記録 {LOG.relative_to(ROOT)}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
