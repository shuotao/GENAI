#!/usr/bin/env python3
"""insert_images.py — 自動插圖工具(plan / apply / verify 三模式,確定性)。

SSoT: prompts/publish_qaqc.md § S4.5.11。原則 6/9:位置「判斷」由 LLM
(Claude Haiku subagent)做,本工具只負責確定性的清單輸出、套用與驗證。

cleaned.md 的段落模型 = **逐行**(md_to_html.py 每個非空行渲染成一個 <p>/<h2>/<h3>),
所以 anchor = 「在第 N 個內容行之後插入圖片行」。

模式:
  --plan    輸出內容行清單 JSON(index/type/preview),給 Haiku 比對用
  --apply   讀 anchors JSON,插入 `![caption](file)`;零省略驗證不過即 rollback
  --verify  md 內每個圖片引用都有 image_notes 條目且 status=inserted

anchors JSON 格式(Haiku subagent 產出):
  [{"file": "IMG_2197.JPG", "after_line": 12, "confidence": 0.9}, ...]
  after_line 是 --plan 輸出的 index;-1 = 「此圖不插入」(重複張/封面/無合理位置),
  跳過並列入報告,不阻擋 apply。每張 described 圖都必須出現在 anchors(完備性)。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

IMG_LINE = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")
IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def content_lines(md_text: str) -> list[tuple[int, str]]:
    """回 [(原始行號, 行內容)],只含非空、非既有圖片行。"""
    out = []
    for i, ln in enumerate(md_text.splitlines()):
        if ln.strip() and not IMG_LINE.match(ln):
            out.append((i, ln))
    return out


def line_type(ln: str) -> str:
    if ln.startswith("### "):
        return "h3"
    if ln.startswith("## "):
        return "h2"
    if ln.startswith("# "):
        return "h1"
    return "para"


def cmd_plan(md_path: Path) -> int:
    lines = content_lines(md_path.read_text(encoding="utf-8"))
    plan = []
    for idx, (_orig, ln) in enumerate(lines):
        preview = ln if len(ln) <= 60 else ln[:40] + "…" + ln[-18:]
        plan.append({"index": idx, "type": line_type(ln), "preview": preview})
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    return 0


def cjk_count(text: str) -> int:
    return len(re.findall(r"[一-鿿㐀-䶿]", text))


def cmd_apply(md_path: Path, notes_path: Path, anchors_path: Path, img_dir: Path) -> int:
    md_text = md_path.read_text(encoding="utf-8")
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
    by_file = {n["file"]: n for n in notes}

    # 1) 先驗 anchors 完備性
    problems = []
    skipped = []  # after_line=-1:此圖不插入(重複張/封面/無合理位置)
    to_insert = []  # (content_line_index, img_file, caption)
    lines = content_lines(md_text)
    for a in anchors:
        f = a["file"]
        note = by_file.get(f)
        if not note:
            problems.append(f"{f}: image_notes.json 無條目")
            continue
        if note.get("status") == "error":
            problems.append(f"{f}: 描述階段 error,不可插入")
            continue
        al = a.get("after_line", -1)
        if al == -1:
            skipped.append(f)
            continue
        if not (0 <= al < len(lines)):
            problems.append(f"{f}: after_line={al} 超出範圍 0-{len(lines)-1}")
            continue
        if not (img_dir / Path(f).name).exists() and not (img_dir / f).exists():
            problems.append(f"{f}: 圖檔不存在於 {img_dir}")
            continue
        to_insert.append((al, f, note.get("caption", "")))
    if skipped:
        print(f"[apply] ○ 不插入(-1,列入報告): {skipped}")
    described = [n["file"] for n in notes if n.get("status") in ("described", "anchored")]
    missing_anchor = set(described) - {a["file"] for a in anchors}
    if missing_anchor:
        problems.append(f"缺 anchor 的圖: {sorted(missing_anchor)}")

    # deck_page 單調約束(§ S4.5.11):有頁碼的投影,頁碼越大 anchor 不得越早。
    # 小違序(常見於 Haiku 複核後相鄰兩張互換)→ 確定性 clamp(往後推到不早於
    # 前一張,只挪一格、不改內容);clamp 後仍矛盾才視為錯誤退回。
    order = sorted((idx for idx, (al, f, _c) in enumerate(to_insert)
                    if by_file.get(f, {}).get("deck_page") is not None),
                   key=lambda i: (by_file[to_insert[i][1]]["deck_page"], to_insert[i][1]))
    prev_line = clamped = -1
    for i in order:
        al, f, cap = to_insert[i]
        if prev_line != -1 and al < prev_line:
            to_insert[i] = (prev_line, f, cap); clamped += 1; al = prev_line
        prev_line = al
    if clamped > 0:
        print(f"[apply] ⚠️ deck_page 單調 clamp:{clamped} 張往後對齊(不早於前一張)")
    # 分佈塌陷 backstop(F2,§ S4.5.11):不論來自 anchors 還是 clamp 累積,
    # 同一插入點疊 > MAX_PER_ANCHOR 張即退回(clamp 可能在此重新製造塌陷)。
    from collections import Counter as _Counter
    MAX_PER_ANCHOR = 2
    line_ct = _Counter(al for al, _f, _c in to_insert if al != -1)
    over = {ln: c for ln, c in line_ct.items() if c > MAX_PER_ANCHOR}
    if over:
        problems.append(
            f"分佈塌陷:{len(over)} 個插入點各疊 >{MAX_PER_ANCHOR} 張(最擠 {max(over.values())} 張)"
            f" — 連續投影片未攤開(clamp 或 anchors 造成);跑 placement_supervisor.py 收斂後再 apply(§ S4.5.11)")
    # needs_review 提示(不擋,列出給人工/agent 複核)
    review = [f for _al, f, _c in to_insert if by_file.get(f, {}).get("needs_review")]
    if review:
        print(f"[apply] ⚠️ needs_review(無頁碼、位置天生模糊,請複核): {review}")
    if problems:
        print("[apply] ✗ anchors 驗證失敗:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from pipeline_logger import log_stage, enqueue_improvement  # noqa: E402
            log_stage(md_path.parent, "S4.5-insert", "insert_images.py", "fail",
                      metrics={"problems": len(problems)}, detail="; ".join(problems[:5]))
            for p in problems:
                enqueue_improvement("S4.5-insert", md_path.parent.name, p)
        except Exception:  # noqa: BLE001 — logger 缺席不影響 apply 結果
            pass
        return 1

    # 2) 套用:按原始行號由後往前插(避免位移),圖片行 = 獨立一行
    orig_lines = md_text.splitlines()
    inserts = sorted(((lines[al][0], f, cap) for al, f, cap in to_insert), reverse=True)
    for orig_idx, f, cap in inserts:
        orig_lines.insert(orig_idx + 1, f"![{cap}]({f})")
    new_text = "\n".join(orig_lines) + "\n"

    # 3) 零省略驗證:原內容行(順序+內容)完全不變、CJK 正文字數只增不減、每張圖恰一次
    old_content = [ln for _i, ln in content_lines(md_text)]
    new_content = [ln for _i, ln in content_lines(new_text)]
    checks = []
    checks.append(("原內容行 1:1 不變", old_content == new_content))
    checks.append(("CJK 正文字數不變",
                   cjk_count("\n".join(old_content)) == cjk_count("\n".join(new_content))))
    for _al, f, _cap in to_insert:
        cnt = len(re.findall(re.escape(f"({f})"), new_text))
        checks.append((f"{f} 恰插一次", cnt == 1))
    failed = [name for name, ok in checks if not ok]
    if failed:
        print(f"[apply] ✗ 零省略驗證失敗,rollback: {failed}", file=sys.stderr)
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from pipeline_logger import log_stage, enqueue_improvement  # noqa: E402
            log_stage(md_path.parent, "S4.5-insert", "insert_images.py", "fail",
                      metrics={"failed_checks": len(failed)}, detail="; ".join(failed))
            enqueue_improvement("S4.5-insert", md_path.parent.name,
                                 f"零省略驗證失敗,rollback: {failed}")
        except Exception:  # noqa: BLE001 — logger 缺席不影響 apply 結果
            pass
        return 1

    # 4) 落盤 + 回寫 image_notes 狀態
    bak = md_path.with_suffix(".md.pre-images.bak")
    bak.write_text(md_text, encoding="utf-8")
    md_path.write_text(new_text, encoding="utf-8")
    a_by_file = {a["file"]: a for a in anchors}
    for n in notes:
        if n["file"] in {f for _al, f, _c in to_insert}:
            src = a_by_file[n["file"]]
            n["anchor"] = {"para_index": src["after_line"],
                           "confidence": src.get("confidence"),
                           "engine": src.get("engine", "haiku")}
            n["status"] = "inserted"
    notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[apply] ✓ 插入 {len(to_insert)} 張(備份: {bak.name});驗證全過")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_logger import log_stage  # noqa: E402
        log_stage(md_path.parent, "S4.5-insert", "insert_images.py", "pass",
                  metrics={"inserted": len(to_insert), "skipped": len(skipped)},
                  detail=f"backup={bak.name}")
    except Exception:  # noqa: BLE001 — logger 缺席不影響 apply 結果
        pass
    return 0


def cmd_verify(md_path: Path, notes_path: Path) -> int:
    md_text = md_path.read_text(encoding="utf-8")
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else []
    by_file = {n["file"]: n for n in notes}
    bad = []
    refs = [m for m in IMG_REF.findall(md_text) if not m.startswith("http")]
    for ref in refs:
        n = by_file.get(ref) or by_file.get(Path(ref).name)
        if not n:
            bad.append(f"{ref}: 無 image_notes 條目")
        elif n.get("status") != "inserted":
            bad.append(f"{ref}: status={n.get('status')}(應為 inserted)")
    if bad:
        print("[verify] ✗")
        for b in bad:
            print(f"  - {b}")
        return 1
    print(f"[verify] ✓ md 內 {len(refs)} 個圖片引用皆有 inserted 條目")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="自動插圖(§ S4.5.11)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--md", default="cleaned.md", help="相對 session 的 md 檔名")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    ap.add_argument("--anchors", help="--apply 用的 anchors JSON 路徑")
    a = ap.parse_args()

    sdir = Path(a.session).resolve()
    md_path = sdir / a.md
    notes_path = sdir / "image_notes.json"
    if a.plan:
        return cmd_plan(md_path)
    if a.apply:
        if not a.anchors:
            print("--apply 需要 --anchors", file=sys.stderr)
            return 2
        return cmd_apply(md_path, notes_path, Path(a.anchors), sdir)
    return cmd_verify(md_path, notes_path)


if __name__ == "__main__":
    sys.exit(main())
