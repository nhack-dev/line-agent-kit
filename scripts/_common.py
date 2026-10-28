"""scripts/ で共通に使う小さな道具（標準ライブラリだけ）。"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> dict[str, str]:
    """.env を読む（KEY=VALUE の行だけ）。環境変数が先に勝つ。"""
    env: dict[str, str] = {}
    p = path or ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(env) + [
        "LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET", "WORKER_URL", "ADMIN_TOKEN",
        "LINE_API_BASE", "LINE_DATA_API_BASE", "STRIPE_WEBHOOK_SECRET",
    ]:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def need(env: dict[str, str], *keys: str) -> None:
    missing = [k for k in keys if not env.get(k)]
    if missing:
        print(f"[止まりました] .env に {', '.join(missing)} がありません。.env.example を見て足してください。")
        sys.exit(2)


def line_base(env: dict[str, str]) -> str:
    return env.get("LINE_API_BASE") or "https://api.line.me"


def line_data_base(env: dict[str, str]) -> str:
    return env.get("LINE_DATA_API_BASE") or env.get("LINE_API_BASE") or "https://api-data.line.me"


def http(method: str, url: str, *, token: str | None = None, body: bytes | dict | None = None,
         headers: dict[str, str] | None = None, content_type: str = "application/json",
         timeout: int = 30) -> tuple[int, dict | str]:
    """HTTP を1回。戻り値は (ステータス, JSON か文字列)。例外は出さずにステータスで返す。"""
    h = {"User-Agent": "line-agent-kit/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = content_type
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", "replace")
            status = res.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except urllib.error.URLError as e:
        return 0, f"つながりませんでした: {e.reason}"
    try:
        return status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return status, raw


def mode_banner(go: bool) -> None:
    print("== 本番（--go）: 実際に送ります ==" if go else "== 試し（dry-run）: 何も送りません。送るときは --go ==")
