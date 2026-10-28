#!/usr/bin/env python3
"""リッチメニュー（トーク画面の下のメニュー）を作って全員の既定にする。既定は試し。

  python3 scripts/richmenu.py --spec templates/richmenu/menu-2x3.json --placeholder logs/menu.png
      → 区切り線だけの仮の画像を作る（本番の画像はデザインして差し替える）
  python3 scripts/richmenu.py --spec templates/richmenu/menu-2x3.json --image logs/menu.png
      → 形と画像を確かめるだけ
  python3 scripts/richmenu.py --spec ... --image ... --go
      → 作る → 画像を上げる → 全員の既定にする
  python3 scripts/richmenu.py --list            （読むだけ）

画像の決まり（LINE の公式の決まり）: JPEG か PNG・幅 800〜2500px・高さ 250px 以上・幅÷高さ 1.45 以上・1MB まで。
上げた画像は差し替えられないので、変えるときはメニューごと作り直す（古いものは --delete <id>）。
"""
from __future__ import annotations

import os as _ng_os, sys as _ng_sys  # N-Hack 専用の門（下の3行を消すとこのキットは動きません）
_ng_sys.path.insert(0, _ng_os.path.dirname(_ng_os.path.abspath(__file__)))
import nhack_gate as _nhack_gate  # noqa: E402,F401


import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import http, line_base, line_data_base, load_env, mode_banner, need  # noqa: E402


def image_size(data: bytes) -> tuple[str, int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg", w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise SystemExit("PNG か JPEG ではありません")


def check_image(data: bytes) -> str:
    ctype, w, h = image_size(data)
    errs = []
    if not 800 <= w <= 2500:
        errs.append(f"幅 {w}px（800〜2500）")
    if h < 250:
        errs.append(f"高さ {h}px（250以上）")
    if w / h < 1.45:
        errs.append(f"幅÷高さ {w / h:.2f}（1.45以上）")
    if len(data) > 1024 * 1024:
        errs.append(f"大きさ {len(data) // 1024}KB（1MBまで）")
    print(f"画像: {ctype} {w}x{h} {len(data) // 1024}KB")
    if errs:
        raise SystemExit("画像が決まりに合いません: " + "・".join(errs))
    return ctype


def check_spec(spec: dict) -> None:
    W, H = spec["size"]["width"], spec["size"]["height"]
    if not spec.get("chatBarText") or len(spec["chatBarText"]) > 14:
        raise SystemExit("chatBarText（メニューの名前）は1〜14字")
    if not 1 <= len(spec.get("areas", [])) <= 20:
        raise SystemExit("areas（押せる場所）は1〜20個")
    for i, a in enumerate(spec["areas"]):
        b = a["bounds"]
        if b["x"] + b["width"] > W or b["y"] + b["height"] > H:
            raise SystemExit(f"areas[{i}] がメニューの外にはみ出しています")
        print(f"  押せる場所 {i + 1}: {a['action'].get('label', '')} → {a['action']['type']} "
              f"{a['action'].get('data') or a['action'].get('text') or a['action'].get('uri', '')}")


def placeholder_png(spec: dict, path: Path) -> None:
    """区切り線だけの仮の画像（文字は入らない）を標準ライブラリだけで作る。"""
    W, H = spec["size"]["width"], spec["size"]["height"]
    lines_x = {a["bounds"]["x"] for a in spec["areas"]} | {W - 1}
    lines_y = {a["bounds"]["y"] for a in spec["areas"]} | {H - 1}
    bg, fg = (245, 245, 240), (90, 90, 90)
    rows = []
    for y in range(H):
        if y in lines_y or (y - 1) in lines_y:
            row = bytes(fg) * W
        else:
            row = bytearray(bytes(bg) * W)
            for x in lines_x:
                for xx in (x, x + 1):
                    if 0 <= xx < W:
                        row[xx * 3:xx * 3 + 3] = bytes(fg)
            row = bytes(row)
        rows.append(b"\x00" + row)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    print(f"仮の画像を作りました: {path}（{len(png) // 1024}KB）")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec")
    ap.add_argument("--image")
    ap.add_argument("--placeholder", help="仮の画像をこの場所に作る")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--delete")
    ap.add_argument("--go", action="store_true")
    args = ap.parse_args()

    env = load_env()
    if args.list:
        need(env, "LINE_CHANNEL_ACCESS_TOKEN")
        st, r = http("GET", f"{line_base(env)}/v2/bot/richmenu/list", token=env["LINE_CHANNEL_ACCESS_TOKEN"])
        st2, d = http("GET", f"{line_base(env)}/v2/bot/user/all/richmenu", token=env["LINE_CHANNEL_ACCESS_TOKEN"])
        for m in (r.get("richmenus", []) if isinstance(r, dict) else []):
            mark = "（既定）" if isinstance(d, dict) and d.get("richMenuId") == m["richMenuId"] else ""
            print(f"{m['richMenuId']} {m['name']} {mark}")
        return

    mode_banner(args.go)
    if args.delete:
        if args.go:
            need(env, "LINE_CHANNEL_ACCESS_TOKEN")
            st, r = http("DELETE", f"{line_base(env)}/v2/bot/richmenu/{args.delete}", token=env["LINE_CHANNEL_ACCESS_TOKEN"])
            print(f"削除: {st} {r}")
        else:
            print(f"{args.delete} を消します（--go で実行）")
        return

    if not args.spec:
        raise SystemExit("--spec が要ります")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    check_spec(spec)
    if args.placeholder:
        placeholder_png(spec, Path(args.placeholder))
        args.image = args.image or args.placeholder
    if not args.image:
        print("形は大丈夫です。画像は --image で渡す（仮なら --placeholder）")
        return
    data = Path(args.image).read_bytes()
    ctype = check_image(data)
    _, w, h = image_size(data)
    if (w, h) != (spec["size"]["width"], spec["size"]["height"]):
        raise SystemExit(f"画像 {w}x{h} と spec の size が違います")
    if not args.go:
        print("試しなのでここまで。作るときは --go")
        return

    need(env, "LINE_CHANNEL_ACCESS_TOKEN")
    tok = env["LINE_CHANNEL_ACCESS_TOKEN"]
    st, r = http("POST", f"{line_base(env)}/v2/bot/richmenu", token=tok, body=spec)
    if st != 200:
        raise SystemExit(f"作れませんでした: {st} {r}")
    rid = r["richMenuId"]
    print(f"作りました: {rid}")
    st, r = http("POST", f"{line_data_base(env)}/v2/bot/richmenu/{rid}/content", token=tok, body=data, content_type=ctype)
    if st != 200:
        raise SystemExit(f"画像を上げられませんでした: {st} {r}（{rid} は --delete で消してから作り直す）")
    st, r = http("POST", f"{line_base(env)}/v2/bot/user/all/richmenu/{rid}", token=tok)
    print(f"全員の既定にしました: {st} {r if st != 200 else ''}")


if __name__ == "__main__":
    main()
