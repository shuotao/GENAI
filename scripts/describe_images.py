#!/usr/bin/env python3
"""describe_images.py — 圖片理解 orchestrator(確定性外殼,LLM 只做看圖判斷)。

SSoT: prompts/publish_qaqc.md § S4.5.11。CLAUDE.md 原則 5/6/9 對齊:
- 引擎:Antigravity CLI headless(OAuth login 通道,原則 5 合法)。
  單引擎;失敗同引擎重試 2 次(退避 5s);連續 N 張失敗即中止整批。
- 色碼(palette_hex)用 PIL 確定性抽取(原則 6)。
- 逐張串行、逐張落盤、可續跑(原則 6/9);已 described 的跳過。

用法:
    python3 scripts/describe_images.py --session sessions/<slug> \
        [--model "Gemini 3.5 Flash (Medium)"] [--limit N] [--max-consecutive-fails N]

產物: sessions/<slug>/image_notes.json(list[dict],schema 見 § S4.5.11)
完成: 全部 described → 刪 .images_pending.json、metadata.json 記 images stats。
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MODEL = "Gemini 3.5 Flash (Medium)"  # antigravity models 實機清單確認(2026-07-05)
IMG_EXTS = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
CALL_TIMEOUT_S = 480  # 照片型(非投影片)+ 完整 schema prompt 實測需 >240s 餘裕

PROMPT_TEMPLATE = """讀取圖片檔 {img_path},然後只輸出一個 JSON 物件(前後不得有任何其他文字、不得用 markdown code fence),欄位:
{{"text_in_image": "圖中所有文字逐字保留原語言(英文/中文/日文原樣抄錄,不翻譯、不省略;含頁碼)",
  "layout": [{{"region": "區塊位置(如:標題/左欄/右下角)", "content": "該區塊的內容與構圖描述"}}],
  "speaker_view": "以講者(演講者)角度 1-2 句話介紹這張圖在講什麼",
  "audience_view": "以聽眾角度 1-2 句話描述看到什麼、注意力落在哪",
  "content_signal": ["3-5 個可在逐字稿中檢索到的錨點詞(專名/產品名/地名/數字),不要通用詞"],
  "caption": "12-20 字的圖片摘要,必須含可定位的具體實體(哪個地點/產品/主題),不要寫『介紹會場環境』這種通用句"}}
禁令:不要描述照片的拍攝狀態(上下顛倒、側轉、反光、拍攝角度)——那是拍攝 meta,與內容無關;把預算花在可定位的實體詞上。"""


# ── 確定性:PIL 主色抽取(k-means top-5 hex)──
def extract_palette(img_path: Path, n: int = 5) -> list[str]:
    from PIL import Image
    im = Image.open(img_path).convert("RGB")
    im.thumbnail((200, 200))
    # PIL 自帶 median-cut 量化 = 確定性,免手寫 k-means
    q = im.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)  # [(count, palette_idx)]
    out = []
    for _cnt, idx in counts[:n]:
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        out.append(f"#{r:02x}{g:02x}{b:02x}")
    return out


# ── JSON 抽取:從 LLM 輸出撈第一個平衡的 {...}(容忍前後 prose / code fence)──
def extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    return None


REQUIRED_FIELDS = ("text_in_image", "layout", "speaker_view", "audience_view", "caption")


# ── 確定性:從 text_in_image 抽投影片頁碼(deck_page)──
# QC 實測(2026-07-05,0704CC):18/20 張投影自帶「N/48 頁」樣式頁碼,且頁碼序
# 與人工插圖行序完全同序 → 頁碼是免費的單調排序鍵(§ S4.5.11)。
_PAGE_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


_SEQ_RE = re.compile(r"(\d{2,})\.[a-zA-Z]+$")  # 副檔名前的序號 = 演講時序(≥2 位;含 01.png / happy-01.png / -0232.png)


def extract_deck_page(text: str, filename: str = "") -> int | None:
    """deck_page = 演講時序代理。**優先用檔名序號 `-NNNN`**(擷取/匯出順序,最可靠;
    影片截圖、依序命名的匯出圖皆適用);沒有序號檔名才 fallback 投影片內印頁碼 `N/M`。
    (內印頁碼會被 demo 畫面裡的數字如攻擊回合 1/6、token 數污染,故只當備援。)"""
    m = _SEQ_RE.search(filename)
    if m:
        return int(m.group(1))
    candidates = [(int(a), int(b)) for a, b in _PAGE_RE.findall(text)
                  if int(b) >= 5 and int(a) <= int(b)]  # 排除日期/比例等雜訊
    return candidates[-1][0] if candidates else None


def validate(d: dict) -> list[str]:
    missing = [k for k in REQUIRED_FIELDS if not d.get(k)]
    if not missing and not isinstance(d.get("layout"), list):
        missing.append("layout(須為 list)")
    return missing


# ── EXIF 轉正:手機側拍照帶 orientation tag,LLM 讀原始像素會看到顛倒/側轉的圖。
#    送描述前先 exif_transpose 到 session/.img_norm/ 暫存(原檔不動;原則 1 精神)──
def normalized_copy(img_path: Path, session_dir: Path) -> Path:
    from PIL import Image, ImageOps
    im = Image.open(img_path)
    fixed = ImageOps.exif_transpose(im)
    if fixed.size == im.size and fixed.tobytes() == im.tobytes():
        return img_path  # 無 EXIF 旋轉 → 用原檔
    tmp_dir = session_dir / ".img_norm"
    tmp_dir.mkdir(exist_ok=True)
    out = tmp_dir / img_path.name
    fixed.convert("RGB").save(out, "JPEG", quality=90)
    return out


# ── LLM 呼叫(單一引擎 Antigravity;無 fallback,見上方 docstring)──
def call_antigravity(img_path: Path, session_dir: Path, model: str) -> str:
    prompt = PROMPT_TEMPLATE.format(img_path=img_path)
    r = subprocess.run(
        ["antigravity", "-p", prompt, "--add-dir", str(session_dir),
         "--model", model, "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=CALL_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"antigravity rc={r.returncode}: {r.stderr[:200]}")
    return r.stdout


def describe_one(img_path: Path, session_dir: Path, model: str) -> tuple[dict, str]:
    """回 (描述 dict, 實際引擎字串)。同引擎重試 2 次(指數退避),全掛 raise。"""
    last_err = None
    for attempt in (1, 2):
        try:
            raw = call_antigravity(img_path, session_dir, model)
            d = extract_json(raw)
            if d is None:
                raise RuntimeError(f"無法從輸出抽出 JSON(前 120 字: {raw[:120]!r})")
            missing = validate(d)
            if missing:
                raise RuntimeError(f"缺欄位: {missing}")
            return d, f"antigravity/{model}"
        except Exception as e:  # noqa: BLE001 — 重試是本函式的職責
            last_err = e
            print(f"    [antigravity 第{attempt}次失敗] {e}", file=sys.stderr)
            if attempt == 1:
                time.sleep(5)
    raise RuntimeError(f"antigravity 兩次皆失敗: {last_err}")


# ── 確定性:描述伴讀 images_readme.md(§ S4.5.11「描述伴讀與人機分流」)──
# 讓「自己手排圖」的使用者在放圖前先看見簡報中沒注意到的細節(逐字稿/雙視角/圖中文字)。
# 純確定性:從 image_notes 逐張渲染,不打任何引擎。
README_TEXT_LIMIT = 200  # text_in_image 摘錄上限(字元)


def write_images_readme(session_dir: Path, notes: list[dict]) -> Path:
    """從 image_notes 產 sessions/<slug>/images_readme.md(描述伴讀)。

    每張圖一節:`### <檔名>` + `![](<檔名>)` + caption + speaker_view/audience_view
    (各一行)+ text_in_image 摘錄(≤200 字,code block)。回傳寫出的路徑。
    """
    session_dir = Path(session_dir)
    lines: list[str] = [
        f"# 圖片描述伴讀 — {session_dir.name}",
        "",
        f"共 {len(notes)} 張。放圖前先讀:每張圖的雙視角敘述與圖中文字,",
        "常含簡報當下沒注意到的細節(§ S4.5.11 描述伴讀與人機分流)。",
        "",
    ]
    for n in notes:
        fname = n.get("file", "")
        lines.append(f"### {fname}")
        lines.append("")
        lines.append(f"![]({fname})")
        lines.append("")
        caption = (n.get("caption") or "").strip()
        if caption:
            lines.append(caption)
            lines.append("")
        sv = (n.get("speaker_view") or "").strip()
        av = (n.get("audience_view") or "").strip()
        if sv:
            lines.append(f"- **講者視角**:{sv}")
        if av:
            lines.append(f"- **聽眾視角**:{av}")
        if sv or av:
            lines.append("")
        text = (n.get("text_in_image") or "").strip()
        if text:
            excerpt = text[:README_TEXT_LIMIT]
            if len(text) > README_TEXT_LIMIT:
                excerpt += "…"
            lines.append("圖中文字摘錄:")
            lines.append("")
            lines.append("```")
            lines.append(excerpt)
            lines.append("```")
            lines.append("")
    out = session_dir / "images_readme.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="圖片理解 orchestrator(§ S4.5.11)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="只處理前 N 張(smoke/測試用)")
    ap.add_argument("--max-consecutive-fails", type=int, default=3,
                    help="連續失敗達此數即中止整批(原則 9,別在死路裡空轉;預設 3)")
    ap.add_argument("--readme-only", action="store_true",
                    help="不打 antigravity,只從既有 image_notes.json 重產 images_readme.md")
    a = ap.parse_args()

    sdir = Path(a.session).resolve()

    if a.readme_only:
        notes_path = sdir / "image_notes.json"
        if not notes_path.exists():
            print(f"[images] {notes_path} 不存在,無法產 readme", file=sys.stderr)
            return 1
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
        out = write_images_readme(sdir, notes)
        print(f"[images] 描述伴讀已重產 → {out}({len(notes)} 節)")
        return 0

    img_dir = sdir / "images"
    scan_dir = img_dir if img_dir.is_dir() else sdir
    images = sorted(p for p in scan_dir.iterdir()
                    if p.is_file() and p.suffix in IMG_EXTS and p.name != "cover.jpg")
    if not images:
        print(f"[images] {scan_dir} 無圖片,跳過")
        return 0
    if a.limit:
        images = images[: a.limit]

    notes_path = sdir / "image_notes.json"
    notes: list[dict] = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else []
    by_file = {n["file"]: n for n in notes}

    done = errs = 0
    consecutive_fails = 0
    for i, img in enumerate(images, 1):
        rel = img.name if scan_dir == sdir else f"images/{img.name}"
        existing = by_file.get(rel)
        if existing and existing.get("status") in ("described", "anchored", "inserted"):
            print(f"[{i}/{len(images)}] {rel} 已 described,跳過")
            continue
        print(f"[{i}/{len(images)}] {rel} …")
        t0 = time.time()
        palette = extract_palette(img)  # 確定性,先算
        send = normalized_copy(img, sdir)  # EXIF 轉正(顛倒側拍照防呆)
        try:
            d, engine_tag = describe_one(send, sdir, a.model)
        except RuntimeError as e:
            print(f"  ✗ {e}", file=sys.stderr)
            by_file[rel] = {**(existing or {}), "file": rel, "palette_hex": palette,
                            "status": "error", "error": str(e)[:300]}
            errs += 1
            consecutive_fails += 1
            if consecutive_fails >= a.max_consecutive_fails:
                notes = [by_file[k] for k in sorted(by_file)]
                notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[images] ✗ 連續 {consecutive_fails} 張失敗,中止整批"
                      f"(疑似引擎層級問題,不是單張圖的偶發錯誤 — 檢查 antigravity 登入狀態"
                      f"再重跑,本工具可續跑)。", file=sys.stderr)
                return 2
        else:
            consecutive_fails = 0
            deck_page = extract_deck_page(d["text_in_image"], rel)  # 內印頁碼 → 檔名序號 fallback
            by_file[rel] = {"file": rel, "palette_hex": palette,
                            "text_in_image": d["text_in_image"], "layout": d["layout"],
                            "speaker_view": d["speaker_view"], "audience_view": d["audience_view"],
                            "content_signal": d.get("content_signal") or [],
                            "caption": d["caption"], "deck_page": deck_page,
                            "needs_review": deck_page is None,  # 無頁碼(場地照等)天生模糊 → 人工複核
                            "anchor": (existing or {}).get("anchor"),
                            "engine": engine_tag, "status": "described"}
            done += 1
            print(f"  ✓ {time.time()-t0:.0f}s | caption: {d['caption']}")
        # 逐張落盤(可續跑)
        notes = [by_file[k] for k in sorted(by_file)]
        notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")

    total_described = sum(1 for n in by_file.values() if n.get("status") in ("described", "anchored", "inserted"))
    print(f"[images] 本輪 {done} 張完成 / {errs} 張失敗 | 累計 described {total_described}/{len(images)}")

    if total_described == len(images) and not a.limit:
        readme = write_images_readme(sdir, notes)  # 描述伴讀(§ S4.5.11)
        print(f"[images] 描述伴讀 → {readme}")
        marker = sdir / ".images_pending.json"
        if marker.exists():
            marker.unlink()
            print("[images] 全數完成 → 已刪 .images_pending.json")
        meta_path = sdir / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.setdefault("qaqc", {})["images"] = {
                "status": "done", "count": len(images), "actor": "describe_images.py",
                "engine": "antigravity", "model": a.model}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
