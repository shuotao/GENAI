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
  2') 或交 Gemini 4 Hydrogen 逐張覆核(2026-11-22 起預設;取代 Sonnet 分組 subagent):
     python3 scripts/anchor_review.py review --session sessions/<slug> \
         --packet <packet.json> [--model gemini-4-hydrogen-medium] [--out reviews.json]
     逐張呼叫 agy headless(附圖檔路徑,模型必須親自開圖),本地先跑 R2/R3 單張檢查,
     不過就把錯誤回饋重問一次;逐張落盤、可續跑。仍需 3) merge 做 R1–R5 總驗收。
  2'') 覆核者回報「正確位置不在候選視窗」時(監管提案漂移,常見於無頁碼的標題/收尾頁):
     python3 scripts/anchor_review.py override --session <dir> --anchors <supervised.json> \
         --reviews <reviews.json> page-087.png=301[:理由] ...
     改該圖提案 → 重產 packet(他圖視窗不變)→ 寫統籌者裁決(evidence 取該行開頭),之後照常 merge。
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


def repair_order(packet: list[dict], reviews: list[dict], max_per_anchor: int) -> list[tuple]:
    """確定性收尾(2026-11-22):逐張獨立覆核時,相鄰投影片常各自選了彼此前後的段落
    (講同一段)→ R4 逆位 / R5 疊太多。依 packet(deck_page)順序掃描:after_line 不得早於前一張、
    單段 ≤ max_per_anchor、非正文行跳過,超出即順延到下一個正文行;evidence 改取該行開頭。
    只做機械順延,不做語意判斷;順延超出候選視窗即放棄(交回人工)。回傳變更清單。"""
    import re as _re
    by = {r["file"]: r for r in reviews}
    prev, cnt, changed = -1, Counter(), []
    for p in packet:
        r = by.get(p["file"])
        if not r or r.get("verdict") == "drop" or r.get("after_line", -1) < 0:
            continue
        win = {w["index"]: w for w in p["window"]}
        al = max(r["after_line"], prev)
        while al in win and (cnt[al] >= max_per_anchor or win[al]["type"] != "para"):
            al += 1
        if al not in win:
            continue  # 視窗內放不下 → 交給 merge 報錯
        if al != r["after_line"]:
            changed.append((p["file"], r["after_line"], al))
            txt = _re.sub(r"^[^：]{1,20}：", "", win[al]["text"])
            r.update(after_line=al, evidence=txt[:14],
                     verdict="keep" if al == p["current_after_line"] else "move",
                     reason=(r.get("reason", "") + "(repair-order:保投影片順序/單段上限,機械順延)"))
        cnt[al] += 1
        prev = al
    return changed


def cmd_merge(a) -> int:
    sdir = Path(a.session)
    packet = _load(Path(a.packet))
    reviews = _load(Path(a.reviews))
    if a.repair_order:
        ch = repair_order(packet, reviews, a.max_per_anchor)
        print(f"[merge] repair-order 順延 {len(ch)} 張:{ch}")
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


REVIEW_PROMPT = """You are reviewing where ONE lecture slide image should be inserted into a Chinese (zh-TW) lecture transcript.
1. Open and look at the image file: {img}
   (You MUST open the image itself; the text below is only a helper.)
2. Slide helper info — caption: {caption}
   OCR: {ocr}
   speaker view: {speaker}
   audience view: {audience}
3. Candidate transcript lines (index: [type] text). The slide is currently after line {cur}.
{window}

Rule: the slide goes AFTER the paragraph where the lecturer is explaining / has just started explaining this slide's content
(end of the explaining paragraph, never directly under a heading). A section-title slide goes after the first paragraph that opens that section.
Keep the current position unless another candidate line is clearly better. Use "drop" only for an exact duplicate or a slide with no reasonable spot.
Only choose a line whose type is "para".

Output ONLY one JSON object, no prose, no code fence:
{{"verdict": "keep|move|drop", "after_line": <int index from the candidates, or -1 for drop>,
  "evidence": "<copy 8-20 characters VERBATIM from the chosen line's text>",
  "reason": "<one sentence in Traditional Chinese: which slide content the lecturer explains in that line>",
  "opened_image": true}}
{feedback}"""


def _check_one(p: dict, r: dict) -> list[str]:
    """單張版 R2/R3(與 merge 同口徑),讓 review 當場退件重問。"""
    if r.get("verdict") not in ("keep", "move", "drop"):
        return [f"verdict 必須是 keep/move/drop,得到 {r.get('verdict')!r}"]
    if r["verdict"] == "drop":
        return []
    win = {w["index"]: w for w in p["window"]}
    al = r.get("after_line")
    if al not in win:
        return [f"after_line={al} not in candidates {min(win)}-{max(win)}"]
    errs = []
    if win[al]["type"] != "para" and al != 0:
        errs.append(f"line {al} is a heading ({win[al]['type']}); choose a para line")
    ev = (r.get("evidence") or "").strip()
    if len(ev) < MIN_EVIDENCE or ev not in win[al]["text"]:
        errs.append(f"evidence {ev[:30]!r} is not a verbatim substring (>= {MIN_EVIDENCE} chars) of line {al}")
    if r["verdict"] == "keep" and al != p["current_after_line"]:
        errs.append("verdict=keep but after_line differs from current; use move")
    return errs


def cmd_review(a) -> int:
    from describe_images import run_agy, extract_json, resolve_model
    sdir = Path(a.session).resolve()
    packet = _load(Path(a.packet))
    model = resolve_model(a.model)
    dst = Path(a.out) if a.out else sdir / "anchor_reviews.json"
    done = {r["file"]: r for r in (_load(dst) if dst.exists() else [])}
    fails = 0
    for i, p in enumerate(packet, 1):
        if p["file"] in done:
            continue
        img = sdir / p["file"]
        window = "\n".join(f"{w['index']}: [{w['type']}] {w['text']}" for w in p["window"])
        feedback, rec = "", None
        for attempt in (1, 2, 3):
            prompt = REVIEW_PROMPT.format(img=img, caption=p.get("caption"), ocr=(p.get("ocr") or "")[:1500],
                                          speaker=p.get("speaker_view"), audience=p.get("audience_view"),
                                          cur=p["current_after_line"], window=window, feedback=feedback)
            try:
                r = extract_json(run_agy(prompt, sdir, model, timeout_s=a.timeout))
            except RuntimeError as e:
                print(f"  [{p['file']}] 第{attempt}次呼叫失敗:{e}", file=sys.stderr)
                continue
            if not r:
                feedback = "\nPrevious answer was not valid JSON. Output only the JSON object."
                continue
            errs = _check_one(p, r)
            if not errs:
                rec = {"file": p["file"], "verdict": r["verdict"],
                       "after_line": -1 if r["verdict"] == "drop" else r["after_line"],
                       "evidence": r.get("evidence", ""), "reason": r.get("reason", ""),
                       "opened_image": bool(r.get("opened_image")), "engine": f"agy/{model}"}
                break
            feedback = "\nYour previous answer was REJECTED: " + "; ".join(errs) + ". Fix it."
        if rec is None:
            fails += 1
            print(f"[review {i}/{len(packet)}] ✗ {p['file']} 三次皆不合格", file=sys.stderr)
            if fails >= a.max_consecutive_fails:
                print("[review] ✗ 連續失敗達熔斷門檻,中止(可續跑)", file=sys.stderr)
                return 2
            continue
        fails = 0
        done[p["file"]] = rec
        dst.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[review {i}/{len(packet)}] {p['file']} {rec['verdict']} → {rec['after_line']}")
    missing = [p["file"] for p in packet if p["file"] not in done]
    print(f"[review] {len(done)}/{len(packet)} 張完成 → {dst}" + (f";缺 {len(missing)} 張" if missing else ""))
    return 1 if missing else 0


def cmd_override(a) -> int:
    """覆核者已讀正文指出正確行、但不在視窗內 → 統籌者裁決(2026-11-22,CS329Z lec4–7 共 10 張)。"""
    import re as _re
    sdir = Path(a.session)
    ov = {}
    for spec in a.items:
        f, rest = spec.split("=", 1)
        line, _, why = rest.partition(":")
        ov[f if "/" in f else f"images/{f}"] = (int(line), why)
    an = _load(Path(a.anchors))
    for x in an:
        if x["file"] in ov:
            x["after_line"] = ov[x["file"]][0]
    Path(a.anchors).write_text(json.dumps(an, ensure_ascii=False, indent=2), encoding="utf-8")
    a.md, a.window, a.out = "cleaned.md", a.window, None
    if cmd_packet(a):
        return 1
    pk = {p["file"]: p for p in _load(sdir / "anchor_review_packet.json")}
    reviews = _load(Path(a.reviews))
    for r in reviews:
        if r["file"] not in ov:
            continue
        ln, why = ov[r["file"]]
        w = {x["index"]: x for x in pk[r["file"]]["window"]}
        if w.get(ln, {}).get("type") != "para":
            print(f"[override] ✗ {r['file']} 第 {ln} 行不是正文段", file=sys.stderr)
            return 1
        r.update(verdict="keep", after_line=ln,
                 evidence=_re.sub(r"^[^：]{1,20}：", "", w[ln]["text"])[:14],
                 reason="統籌者裁決:" + (why or "正確位置不在原候選視窗"), adjudicated="orchestrator")
        print(f"[override] {r['file']} → {ln}")
    Path(a.reviews).write_text(json.dumps(reviews, ensure_ascii=False, indent=1), encoding="utf-8")
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
    rv = sub.add_parser("review", help="Gemini 4 Hydrogen(agy headless)逐張覆核 → reviews JSON")
    rv.add_argument("--session", required=True)
    rv.add_argument("--packet", required=True)
    rv.add_argument("--model", default="gemini-4-hydrogen-medium")
    rv.add_argument("--timeout", type=int, default=300)
    rv.add_argument("--max-consecutive-fails", type=int, default=3)
    rv.add_argument("--out")
    ov = sub.add_parser("override", help="覆核者指出視窗外的正確行 → 改提案、重產 packet、寫統籌者裁決")
    ov.add_argument("--session", required=True)
    ov.add_argument("--anchors", required=True)
    ov.add_argument("--reviews", required=True)
    ov.add_argument("--window", type=int, default=6)
    ov.add_argument("items", nargs="+", help="page-087.png=301[:理由]")
    mg = sub.add_parser("merge")
    mg.add_argument("--session", required=True)
    mg.add_argument("--packet", required=True)
    mg.add_argument("--reviews", required=True)
    mg.add_argument("--max-per-anchor", type=int, default=2)
    mg.add_argument("--repair-order", action="store_true",
                    help="先做確定性收尾(保 deck 順序、單段上限、順延到下一正文行),再驗 R1–R5")
    mg.add_argument("--out")
    a = ap.parse_args()
    return {"packet": cmd_packet, "review": cmd_review, "override": cmd_override, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
