#!/usr/bin/env python3
"""anchor_review.py — 逐張三立場校位(§ S4.5.11「逐張三立場校位」,確定性外殼)。

背景(2026-10-15,AU2026 AS1569):placement_supervisor 只把相關性 warning/fail 的
少數圖交 Haiku 看,其餘「分數過得去」的圖從沒有人拿圖的內容去對照正文確認位置。
使用者裁定這樣太草率 → 每一張圖都要用描述的三立場(OCR 當頁文字 / 講者立場 /
聽眾立場)對照候選段落,確認或校正 after_line,且判斷要**機械可證**。

分工(原則 6):本工具只做確定性的事 —— 產對照包、驗覆核結果、輸出 anchors;
「這張圖該放哪一段」的判斷由對話 agent / subagent 做,寫成 reviews JSON。

用法:
  1) 產對照包(每張圖:三立場 + 目前錨點前後 ±W 行的完整正文)
     python3 scripts/anchor_review.py packet --session sessions/<slug> \
         --anchors sessions/<slug>/anchors_supervised.json [--window 6] [--out <packet.json>]
  2) agent 逐張覆核,寫 reviews JSON(list),每筆:
     {"file": "images/page-07.png", "verdict": "keep|move|drop",
      "after_line": 33, "evidence": "<從 after_line 那一行逐字摘錄、≥6 字>",
      "reason": "一句話:講者在這段解說了圖上的哪個內容"}
  3) 合併校驗 → 新 anchors(可直接餵 insert_images --apply)
     python3 scripts/anchor_review.py merge --session sessions/<slug> \
         --packet <packet.json> --reviews <reviews.json> [--out anchors_reviewed.json]

merge 的硬門(任一不過 → exit 1,不輸出 anchors):
  R1 完備:packet 裡每張圖恰有一筆 review。
  R2 範圍:after_line 落在該圖 packet 的候選視窗內,且是正文段落而非標題行(drop 例外,after_line=-1)。
  R3 證據:evidence 必須逐字出現在 after_line 那一行(證明真的讀了該段,不是憑分數)。
  R4 順序:依 deck_page 排序後 after_line 單調不減(不得逆位,§ S6.11.c 同口徑)。
  R5 分佈:單一 after_line 最多 --max-per-anchor 張(預設 2,§ S6.11.b 同口徑)。
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from insert_images import content_lines, line_type  # noqa: E402

MIN_EVIDENCE = 6
ENGINE_TAG = "tri-view-reviewed"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_packet(a) -> int:
    sdir = Path(a.session)
    lines = content_lines((sdir / a.md).read_text(encoding="utf-8"), skip_quote=True)
    notes = {n["file"]: n for n in _load(sdir / "image_notes.json")}
    anchors = _load(Path(a.anchors))
    anchors.sort(key=lambda x: (notes.get(x["file"], {}).get("deck_page") or 0, x["file"]))
    out = []
    for an in anchors:
        n = notes.get(an["file"])
        if not n:
            print(f"[packet] ✗ {an['file']} 無 image_notes 條目", file=sys.stderr)
            return 1
        cur = an["after_line"]
        lo, hi = max(0, cur - a.window), min(len(lines) - 1, cur + a.window)
        out.append({
            "file": an["file"], "deck_page": n.get("deck_page"), "current_after_line": cur,
            "caption": n.get("caption"),
            "ocr": n.get("text_in_image"),
            "speaker_view": n.get("speaker_view"),
            "audience_view": n.get("audience_view"),
            "window": [{"index": i, "type": line_type(lines[i][1]), "text": lines[i][1],
                        **({"current": True} if i == cur else {})}
                       for i in range(lo, hi + 1)],
        })
    dst = Path(a.out) if a.out else sdir / "anchor_review_packet.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[packet] {len(out)} 張 → {dst}(視窗 ±{a.window} 行)")
    return 0


def cmd_merge(a) -> int:
    sdir = Path(a.session)
    packet = _load(Path(a.packet))
    reviews = _load(Path(a.reviews))
    by_file: dict[str, dict] = {}
    errs: list[str] = []
    for r in reviews:
        if r["file"] in by_file:
            errs.append(f"R1 重複覆核 {r['file']}")
        by_file[r["file"]] = r
    pk_files = {p["file"] for p in packet}
    for f in sorted(set(by_file) - pk_files):
        errs.append(f"R1 覆核了不在 packet 的圖 {f}")

    out, moved, dropped = [], 0, 0
    for p in packet:  # packet 已依 deck_page 排序
        r = by_file.get(p["file"])
        if not r:
            errs.append(f"R1 缺覆核 {p['file']}")
            continue
        verdict, al = r.get("verdict"), r.get("after_line")
        if verdict == "drop":
            al = -1
            dropped += 1
        else:
            win = {w["index"]: w["text"] for w in p["window"]}
            types = {w["index"]: w["type"] for w in p["window"]}
            if al not in win:
                errs.append(f"R2 {p['file']} after_line={al} 不在候選視窗 "
                            f"{min(win)}–{max(win)}")
                continue
            if types[al] != "para" and al != 0:
                errs.append(f"R2 {p['file']} after_line={al} 是標題行({types[al]}),"
                            f"圖要錨在講者解說的段尾,不錨小標下")
            ev = (r.get("evidence") or "").strip()
            if len(ev) < MIN_EVIDENCE or ev not in win[al]:
                errs.append(f"R3 {p['file']} evidence 未逐字出現在第 {al} 行"
                            f"(或短於 {MIN_EVIDENCE} 字):{ev[:30]!r}")
            if verdict == "keep" and al != p["current_after_line"]:
                errs.append(f"R2 {p['file']} verdict=keep 但 after_line 改了"
                            f"({p['current_after_line']}→{al})")
            if al != p["current_after_line"]:
                moved += 1
        out.append({"file": p["file"], "after_line": al, "confidence": 1.0,
                    "engine": ENGINE_TAG, "reason": r.get("reason", ""),
                    "evidence": r.get("evidence", "")})

    placed = [o["after_line"] for o in out if o["after_line"] >= 0]
    for prev, nxt in zip(placed, placed[1:]):
        if nxt < prev:
            errs.append(f"R4 逆位:after_line {prev} 之後出現 {nxt}")
    for line, k in Counter(placed).items():
        if k > a.max_per_anchor:
            errs.append(f"R5 第 {line} 行疊 {k} 張 > {a.max_per_anchor}")

    if errs:
        print(f"[merge] ✗ {len(errs)} 項不過:", file=sys.stderr)
        for e in errs:
            print("  -", e, file=sys.stderr)
        return 1
    dst = Path(a.out) if a.out else sdir / "anchors_reviewed.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[merge] ✓ {len(out)} 張全數覆核(R1–R5 過)| 校正 {moved} 張、不插入 {dropped} 張 → {dst}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="逐張三立場校位(§ S4.5.11)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pk = sub.add_parser("packet")
    pk.add_argument("--session", required=True)
    pk.add_argument("--md", default="cleaned.md")
    pk.add_argument("--anchors", required=True)
    pk.add_argument("--window", type=int, default=6)
    pk.add_argument("--out")
    mg = sub.add_parser("merge")
    mg.add_argument("--session", required=True)
    mg.add_argument("--packet", required=True)
    mg.add_argument("--reviews", required=True)
    mg.add_argument("--max-per-anchor", type=int, default=2)
    mg.add_argument("--out")
    a = ap.parse_args()
    return cmd_packet(a) if a.cmd == "packet" else cmd_merge(a)


if __name__ == "__main__":
    sys.exit(main())
