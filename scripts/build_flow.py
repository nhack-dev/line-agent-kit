#!/usr/bin/env python3
"""config/flow.json を確かめて worker/src/flow.generated.js に書き出す。

  python3 scripts/build_flow.py                      # config/flow.json（無ければ見本）を確かめるだけ
  python3 scripts/build_flow.py --write              # 確かめて worker に書き出す（deploy の前に毎回）
  python3 scripts/build_flow.py --friends 300        # 友だち300人なら月に何通使うかの見積もり

確かめること:
  ・形の誤り（id の重複・無いシナリオやタグへの参照・5通を超える便・日時の書き方）
  ・まとめて送る便（ステップ）に {pay_url} などの差し込みが入っていないか（差し込めないため）
  ・月の通数の見積もりがプランの無料通数を超えないか
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

MAX_TEXT = 5000          # LINE のテキストメッセージの上限（文字）
MAX_MSGS = 5             # 1回の reply / push / multicast に入れられる吹き出しの数
QUICK_REPLY_MAX = 13


def msg_list_errors(where: str, msgs, errors: list[str], allow_vars: bool) -> None:
    if not isinstance(msgs, list):
        errors.append(f"{where}: messages は配列にしてください")
        return
    if len(msgs) > MAX_MSGS:
        errors.append(f"{where}: 吹き出しは {MAX_MSGS} 個までです（いま {len(msgs)} 個）")
    for i, m in enumerate(msgs):
        text = m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)
        if isinstance(m, str) and len(m) > MAX_TEXT:
            errors.append(f"{where}[{i}]: {MAX_TEXT} 字を超えています（{len(m)} 字）")
        if isinstance(m, dict) and "type" not in m:
            errors.append(f"{where}[{i}]: メッセージオブジェクトに type がありません")
        if not allow_vars and re.search(r"\{(pay_url|name|datetime|title|url)\}", text):
            errors.append(f"{where}[{i}]: まとめて送る便には差し込み（{{pay_url}} など）を使えません。"
                          "購入は postback の buy=<商品id> ボタンにしてください")


def check(flow: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    tags_made: set[str] = set(flow.get("follow_tags", [])) | {"optout"}

    msg_list_errors("greeting", flow.get("greeting", []), errors, allow_vars=False)
    if not flow.get("greeting"):
        warns.append("greeting（友だち追加のあいさつ）が空です")

    ids = [k.get("id") for k in flow.get("keywords", [])]
    if len(ids) != len(set(ids)):
        errors.append("keywords の id が重なっています")
    for k in flow.get("keywords", []):
        if k.get("match") not in ("exact", "contains"):
            errors.append(f"keywords.{k.get('id')}: match は exact か contains")
        msg_list_errors(f"keywords.{k.get('id')}.reply", k.get("reply", []), errors, allow_vars=False)
        tags_made |= set(k.get("add_tags", []))

    for sv in flow.get("surveys", []):
        for q in sv.get("questions", []):
            if len(q.get("options", [])) > QUICK_REPLY_MAX:
                errors.append(f"surveys.{sv.get('id')}.{q.get('id')}: 選択肢は {QUICK_REPLY_MAX} 個まで")
            for o in q.get("options", []):
                tags_made |= set(o.get("add_tags", []))
                if len(o.get("label", "")) > 20:
                    warns.append(f"surveys.{sv['id']}.{q['id']}: 「{o['label']}」は20字で切れます")
        tags_made |= set(sv.get("done_tags", []))

    products = flow.get("products", [])
    for p in products:
        tags_made |= set(p.get("add_tags", [f"buyer:{p.get('id')}"]))
        if not str(p.get("payment_link_url", "")).startswith("https://"):
            errors.append(f"products.{p.get('id')}: payment_link_url は https:// から")
        if "XXXX" in str(p.get("payment_link_url", "")):
            warns.append(f"products.{p.get('id')}: payment_link_url が見本のままです")
        if len(products) > 1 and not p.get("payment_link_id"):
            errors.append(f"products.{p.get('id')}: 商品が2つ以上のときは payment_link_id（plink_...）が要ります")
        msg_list_errors(f"products.{p.get('id')}.delivery", p.get("delivery", []), errors, allow_vars=True)

    b = flow.get("booking")
    if b:
        tags_made |= set(b.get("add_tags", []))
        if not b.get("reminders_minutes"):
            warns.append("booking.reminders_minutes が空です（リマインドが出ません）")

    sc_ids = [s.get("id") for s in flow.get("scenarios", [])]
    if len(sc_ids) != len(set(sc_ids)):
        errors.append("scenarios の id が重なっています")
    for sc in flow.get("scenarios", []):
        start = sc.get("start", "")
        if not (start == "follow" or start.startswith("tag:") or start == "manual"):
            errors.append(f"scenarios.{sc.get('id')}: start は follow / tag:<タグ> / manual")
        if start.startswith("tag:") and start[4:] not in tags_made:
            warns.append(f"scenarios.{sc['id']}: start のタグ「{start[4:]}」を付ける所がありません（/admin/tags で付けるなら問題なし）")
        last = -1
        for i, st in enumerate(sc.get("steps", [])):
            where = f"scenarios.{sc['id']}.steps[{i}]"
            if st.get("after_minutes") is None and st.get("after_days") is None:
                errors.append(f"{where}: after_minutes か after_days が要ります")
            if st.get("at") and not re.fullmatch(r"\d{1,2}:\d{2}", st["at"]):
                errors.append(f"{where}: at は 19:00 の形で")
            order = st.get("after_minutes", 0) / 1440 if st.get("after_minutes") is not None else st.get("after_days", 0)
            if order < last:
                errors.append(f"{where}: 前の便より早い時刻になっています（上から順に並べてください）")
            last = order
            msg_list_errors(f"{where}.messages", st.get("messages", []), errors, allow_vars=False)
            for tg in st.get("only_if_tags", []):
                if tg not in tags_made:
                    warns.append(f"{where}: only_if_tags の「{tg}」を付ける所がありません")
    return errors, warns


def estimate(flow: dict, friends: int) -> int:
    """1か月に数えられる通数の見積もり（友だち全員が全ステップを受け取る・予約の半分がリマインドを受け取る想定）。

    reply（あいさつ・キーワード・アンケート・購入リンク）は数えられないので入れない。
    """
    per_friend = 0
    for sc in flow.get("scenarios", []):
        if sc.get("start") == "follow":
            per_friend += len([s for s in sc.get("steps", []) if (s.get("after_days") or 0) < 31])
    reminders = len((flow.get("booking") or {}).get("reminders_minutes", []))
    return friends * per_friend + int(friends * 0.5) * reminders


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flow", default=None, help="既定は config/flow.json（無ければ config/flow.example.json）")
    ap.add_argument("--write", action="store_true", help="worker/src/flow.generated.js に書き出す")
    ap.add_argument("--friends", type=int, default=100, help="通数の見積もりに使う、月に増える友だちの数")
    args = ap.parse_args()

    path = Path(args.flow) if args.flow else ROOT / "config" / "flow.json"
    if not path.exists():
        path = ROOT / "config" / "flow.example.json"
        print(f"config/flow.json が無いので見本を使います: {path.relative_to(ROOT)}")
    flow = json.loads(path.read_text(encoding="utf-8"))
    errors, warns = check(flow)
    for w in warns:
        print(f"  注意: {w}")
    for e in errors:
        print(f"  誤り: {e}")

    est = estimate(flow, args.friends)
    free = flow.get("plan_monthly_free_messages", 200)
    print(f"通数の見積もり: 新しい友だち {args.friends} 人／月 → 約 {est} 通（無料の枠 {free} 通）")
    if est > free:
        print("  注意: 無料の枠を超える見込みです。便を減らすか、プランを上げるか、reply（無料）で返す形に寄せてください")

    if errors:
        print(f"誤り {len(errors)} 件。直してからもう一度。")
        sys.exit(1)
    if args.write:
        out = ROOT / "worker" / "src" / "flow.generated.js"
        out.write_text("// scripts/build_flow.py が作ったファイル。手で直さず config/flow.json を直す\n"
                       f"export default {json.dumps(flow, ensure_ascii=False, indent=2)};\n", encoding="utf-8")
        print(f"書き出しました: {out.relative_to(ROOT)}")
    else:
        print("誤り 0 件。worker に入れるときは --write")


if __name__ == "__main__":
    main()
