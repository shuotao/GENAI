#!/usr/bin/env python3
"""scripts/publish_qaqc.py — Step 6 出版後 QAQC 自動審查腳本

讀 scripts/publish/goodedunote/public/data.js + 各 slug 目錄,對照
prompts/publish_qaqc.md § S6 規則,逐 slug 跑 S6.1–S6.6 檢查。

用法:
    python3 scripts/publish_qaqc.py            # 審查所有非 placeholder 的 book
    python3 scripts/publish_qaqc.py --slug X   # 只審單一 slug

Exit code 0 = 全通過,1 = 任何一項失敗,2 = 環境錯誤(找不到 data.js 等)。

設計:純讀檔,不打網路,不修改任何檔案。可重複跑、可進 CI。
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUB = PROJECT_ROOT / "scripts/publish/goodedunote/public"

# § S4.5.7 shelf → 中文 label(用於檢查 back-link 文字)
SHELF_LABELS = {"public": "公開活動", "seminar": "研討會", "reading": "讀書會"}


# ──────────────────────────────────────────────────────────────────
# data.js 解析(因 JS object 用單引號 + unquoted keys,無法 json.loads)
# ──────────────────────────────────────────────────────────────────
def _match_bracket(s: str, start: int, open_c: str, close_c: str) -> int:
    """從 s[start](必為 open_c)往後找對應的 close_c 索引。會跳過字串內的 bracket。"""
    if s[start] != open_c:
        raise ValueError(f"s[{start}]={s[start]!r} != {open_c!r}")
    depth = 0
    in_str = False
    quote = None
    i = start
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                in_str = False
        else:
            if c in ("'", '"'):
                in_str = True
                quote = c
            elif c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise ValueError(f"no matching {close_c} from index {start}")


def _scalar(book_str: str, key: str, str_or_num: str):
    """從 book object 字串抽 scalar 欄位。str_or_num: 'str' | 'num'。"""
    if str_or_num == "str":
        m = re.search(rf"{key}:\s*['\"]([^'\"]*)['\"]", book_str)
        return m.group(1) if m else None
    else:
        m = re.search(rf"{key}:\s*(\d+|null)", book_str)
        if not m:
            return None
        v = m.group(1)
        return None if v == "null" else int(v)


def _quotes(book_str: str) -> list[str]:
    """抽 quotes: [...] 內的字串(不含巢狀,我們的 quotes 都是 flat string array)。"""
    m = re.search(r"quotes:\s*\[", book_str)
    if not m:
        return []
    arr_start = m.end() - 1  # 指向 '['
    arr_end = _match_bracket(book_str, arr_start, "[", "]")
    body = book_str[arr_start + 1 : arr_end]
    # 抽單引號或雙引號字串
    strs = re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", body)
    return [a or b for a, b in strs]


def parse_data_js(data_js_path: Path) -> list[dict]:
    """回 [{'id': 'public', 'books': [book...]}, ...](placeholder books 也含)。"""
    txt = data_js_path.read_text(encoding="utf-8")
    sh_idx = txt.index("window.SHELVES")
    arr_start = txt.index("[", sh_idx)
    arr_end = _match_bracket(txt, arr_start, "[", "]")
    body = txt[arr_start + 1 : arr_end]

    shelves = []
    i = 0
    while i < len(body):
        if body[i] == "{":
            obj_end = _match_bracket(body, i, "{", "}")
            shelf_str = body[i : obj_end + 1]
            shelves.append(_parse_shelf(shelf_str))
            i = obj_end + 1
        else:
            i += 1
    return shelves


def _parse_shelf(shelf_str: str) -> dict:
    shelf_id = _scalar(shelf_str, "id", "str")
    bm = re.search(r"books:\s*\[", shelf_str)
    if not bm:
        return {"id": shelf_id, "books": []}
    arr_start = bm.end() - 1
    arr_end = _match_bracket(shelf_str, arr_start, "[", "]")
    body = shelf_str[arr_start + 1 : arr_end]

    books = []
    i = 0
    while i < len(body):
        if body[i] == "{":
            obj_end = _match_bracket(body, i, "{", "}")
            books.append(_parse_book(body[i : obj_end + 1]))
            i = obj_end + 1
        else:
            i += 1
    return {"id": shelf_id, "books": books}


def _parse_book(book_str: str) -> dict:
    b = {}
    for k in ("id", "title", "subtitle", "date", "venue", "duration", "url"):
        b[k] = _scalar(book_str, k, "str")
    for k in ("words", "height", "width", "spineShade"):
        b[k] = _scalar(book_str, k, "num")
    b["quotes"] = _quotes(book_str)
    b["placeholder"] = bool(re.search(r"placeholder:\s*true", book_str))
    b["single"] = bool(re.search(r"single:\s*true", book_str))
    return b


# ──────────────────────────────────────────────────────────────────
# Helpers — prose word counting from deployed HTML(for S6.3.b)
# ──────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def count_deployed_chinese_chars(files: list[Path], include_h2: bool = False) -> int:
    """統計 prose 區塊(<p> + <h3>[+ <h2>])內的中文字總和 = § S6.3.b 的『實際內容字數』。

    - 多頁模式:prose 在 session-*.html,標題用 <h3>(session_head_block 的章節 <h2>
      不算內容),故 include_h2=False。
    - 單篇連續模式(single:true):prose 在 index.html,段落標題就是文章內 <h2>,
      要一起算 → include_h2=True。
    """
    tags = "p|h2|h3" if include_h2 else "p|h3"
    block_re = re.compile(rf"<({tags})\b[^>]*>(.*?)</\1>", re.S)
    total = 0
    for p in files:
        html = p.read_text(encoding="utf-8")
        # 切掉 <head>/<script>/<style> 避免抓到 CSS/JS 內偶發 CJK
        html = re.sub(r"<head>.*?</head>", "", html, flags=re.S)
        html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
        html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S)
        for _tag, inner in block_re.findall(html):
            text = _TAG_RE.sub("", inner)  # strip nested <strong> etc.
            total += len(_CJK_RE.findall(text))
    return total


# ──────────────────────────────────────────────────────────────────
# Audit checks(§ S6.1 – S6.6)
# ──────────────────────────────────────────────────────────────────
def audit_book(book: dict, shelf_id: str, pub_dir: Path) -> list[tuple]:
    """回 [(rule_id, ok, detail), ...]。"""
    results = []

    # 從 url 推 slug(必為 `./<slug>/` 或絕對 URL 形式)
    url = book.get("url") or ""
    slug_from_url = None
    if url:
        if url.startswith("./") and url.endswith("/"):
            slug_from_url = url[2:-1]
        else:
            m = re.search(r"/([^/]+)/?$", url.rstrip("/"))
            if m:
                slug_from_url = m.group(1)

    # S6.3 id ↔ url slug 一致
    if slug_from_url:
        ok = book["id"] == slug_from_url
        results.append(("S6.3 id ↔ url slug 一致", ok,
                       f"id={book['id']} url→slug={slug_from_url}" if not ok else ""))
        slug = slug_from_url
    else:
        results.append(("S6.3 url 為 ./<slug>/ 形式", False, f"url={url!r}"))
        slug = book["id"]

    # S6.3 url 為相對(./)路徑
    if url and not url.startswith("./"):
        results.append(("S6.3 url 用相對路徑(./)", False, f"url={url}"))

    slug_dir = pub_dir / slug

    # S6.1 slug 目錄存在
    if not slug_dir.is_dir():
        results.append(("S6.1 slug dir 存在", False, str(slug_dir)))
        return results
    results.append(("S6.1 slug dir 存在", True, slug))

    # S6.1 index.html 必存
    index_path = slug_dir / "index.html"
    has_index = index_path.is_file()
    results.append(("S6.1 index.html 存在", has_index, ""))
    if not has_index:
        return results

    sessions = sorted(slug_dir.glob("session-*.html"))
    pages = [index_path] + sessions

    # S6.1.b 孤兒 session 檔(目錄裡有但 index 沒指向)
    # S6.1.c 斷裂 session 引用(index 指向但檔案不存在)
    index_html = index_path.read_text(encoding="utf-8")
    referenced_sessions = set(re.findall(r'href="(session-\d+\.html)"', index_html))
    actual_sessions = {p.name for p in sessions}
    orphan = sorted(actual_sessions - referenced_sessions)
    dangling = sorted(referenced_sessions - actual_sessions)
    results.append((
        "S6.1.b 無孤兒 session-*.html",
        not orphan,
        f"orphan: {orphan}(目錄有但 index.html 沒引用)" if orphan else f"all {len(actual_sessions)} sessions 都被 index 引用",
    ))
    results.append((
        "S6.1.c 無斷裂 session 引用",
        not dangling,
        f"dangling: {dangling}(index 指向但檔案不存在)" if dangling else f"all {len(referenced_sessions)} index href 都解析到實檔",
    ))

    # S6.8 拆分合理性(2026-07-05 引入)— 拆分單元是「講者(人)」,不是主題標題。
    # 單一講者的一場分享 = 單篇連續(single: true):不得有 session-*.html,正文在單一 <article>。
    # SSoT: prompts/publish_qaqc.md § S4.5 拆分決策 / § S6.8。
    is_single = bool(book.get("single"))
    if is_single:
        results.append((
            "S6.8 拆分合理性(單講者=單篇,無 session 檔)",
            len(sessions) == 0,
            f"single:true 卻有 {len(sessions)} 個 session-*.html(應為 0,單講者不該拆頁)"
            if sessions else "單篇連續,無分頁 ✓",
        ))
        results.append((
            "S6.8 單篇正文在單一 <article>",
            "<article" in index_html,
            "index.html 缺 <article> 連續正文" if "<article" not in index_html else "",
        ))

    # S6.2 back link 統一
    expected_anchor = f"shelf-{shelf_id}"
    expected_label = f"回到{SHELF_LABELS.get(shelf_id, '?')}書架"
    bad_pages_anchor = []
    bad_pages_label = []
    for p in pages:
        html = p.read_text(encoding="utf-8")
        if f'href="../#{expected_anchor}"' not in html:
            bad_pages_anchor.append(p.name)
        if expected_label not in html:
            bad_pages_label.append(p.name)
    results.append((
        "S6.2 back-link anchor 統一",
        not bad_pages_anchor,
        f"failing: {bad_pages_anchor}" if bad_pages_anchor else f"all {len(pages)} pages 含 ../#{expected_anchor}",
    ))
    results.append((
        "S6.2 back-link label 統一",
        not bad_pages_label,
        f"failing: {bad_pages_label}" if bad_pages_label else f"all {len(pages)} pages 含「{expected_label}」",
    ))

    # S6.3 data.js 必填欄位
    required_str = ["id", "title", "subtitle", "date", "venue", "duration", "url"]
    # words/height/width 必須 > 0;spineShade 是配色變體(0 或 1 都合法)
    required_positive_num = ["words", "height", "width"]
    for k in required_str:
        v = book.get(k)
        ok = v is not None and v != ""
        results.append((f"S6.3 data.js {k} 非空", ok, repr(v) if not ok else ""))
    for k in required_positive_num:
        v = book.get(k)
        ok = isinstance(v, int) and v > 0
        results.append((f"S6.3 data.js {k} > 0", ok, repr(v) if not ok else str(v)))
    # spineShade:必須是 0 或 1
    sh = book.get("spineShade")
    ok = sh in (0, 1)
    results.append(("S6.3 data.js spineShade ∈ {0,1}", ok, repr(sh) if not ok else str(sh)))

    qn = len(book.get("quotes", []))
    results.append(("S6.3 quotes 數量 3-4", 3 <= qn <= 4, f"n={qn}"))

    # S6.3.b data.js words 漂移檢查(vs deployed prose CJK 字數)
    # 單篇:prose 在 index.html(含文章內 <h2>);多頁:prose 在 session-*.html。
    prose_files = [index_path] if is_single else sessions
    declared = book.get("words")
    if isinstance(declared, int) and declared > 0 and prose_files:
        actual = count_deployed_chinese_chars(prose_files, include_h2=is_single)
        if actual == 0:
            results.append(("S6.3.b words 漂移檢查", True, "deployed prose 抓不到 CJK 字(可能全是英文書),跳過比對"))
        else:
            drift_pct = abs(declared - actual) / actual * 100
            ok = drift_pct < 10
            severity = "✓ healthy" if drift_pct < 5 else ("⚠ warning" if drift_pct < 10 else "✗ fail")
            results.append((
                "S6.3.b data.js words 漂移 < 10%",
                ok,
                f"declared={declared}, deployed prose CJK={actual}, drift={drift_pct:.1f}% [{severity}]",
            ))

    # S6.4 OG / Twitter meta — 拆兩層:核心(MUST)、圖像(SHOULD)
    og_core_keys = ["og:title", "og:url", "twitter:card"]
    og_image_keys = ["og:image", "twitter:image"]
    bad_core = []
    bad_image = []
    for p in pages:
        html = p.read_text(encoding="utf-8")
        if any(k not in html for k in og_core_keys):
            bad_core.append(p.name)
        if any(k not in html for k in og_image_keys):
            bad_image.append(p.name)
    results.append((
        "S6.4 OG core meta(og:title/url, twitter:card)",
        not bad_core,
        f"failing: {bad_core}" if bad_core else f"all {len(pages)} pages OK",
    ))
    # og:image 為建議:無圖頁面允許省略,但 print 警告供未來改善
    if bad_image:
        results.append((
            "S6.4 OG image meta(建議,不強制)",
            True,  # 不視為失敗
            f"⚠️ {len(bad_image)}/{len(pages)} 頁無 og:image — social share 無預覽縮圖",
        ))
    else:
        results.append((
            "S6.4 OG image meta(建議,不強制)",
            True,
            f"all {len(pages)} pages 含預覽圖",
        ))

    # S6.5 圖片預算
    img_exts = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
    imgs = [f for f in slug_dir.iterdir() if f.is_file() and f.suffix in img_exts]
    total = sum(f.stat().st_size for f in imgs)
    total_mb = total / (1024 * 1024)
    results.append((
        "S6.5 圖片總量 < 10MB",
        total_mb < 10,
        f"{total_mb:.2f}MB across {len(imgs)} imgs",
    ))
    big = [f for f in imgs if f.stat().st_size > 1024 * 1024]
    results.append((
        "S6.5 單張 < 1MB",
        not big,
        f"{len(big)} 張 > 1MB(壓縮失效?)" if big else f"max={max((f.stat().st_size for f in imgs), default=0)//1024}KB" if imgs else "no images",
    ))

    # S6.11 圖文相關性(2026-07-05 引入,§ S4.5.11 / § S6.11)
    # 只在 session 產物有 image_notes.json 時檢查(舊書無 → 跳過不 fail)。
    sessions_root = PROJECT_ROOT / "sessions"
    notes_file = None
    for sess in sessions_root.glob("*/image_notes.json") if sessions_root.is_dir() else []:
        # 以 slug 對 metadata.session_id 或圖檔重疊姑且對映:找含相同圖檔名的 session
        notes_file = sess if slug in sess.parent.name or _notes_match_slug(sess, slug_dir) else notes_file
    if notes_file is None:
        results.append(("S6.11 圖文相關性", True, "無 image_notes.json(舊書/無圖流程),跳過"))
    else:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from img_context_score import score as _score, verdict as _verdict  # noqa: E402
        import json as _json
        notes = {n["file"]: n for n in _json.loads(notes_file.read_text(encoding="utf-8"))}
        bad_corr = []
        checked = 0
        for p in pages:
            html = p.read_text(encoding="utf-8")
            body = re.sub(r"<head>.*?</head>", "", html, flags=re.S)
            # figure 圖與其前後 <p> 文字
            blocks = re.findall(r"<(p|h2|h3|figure)[^>]*>(.*?)</\1>", body, flags=re.S)
            for i, (tag, inner) in enumerate(blocks):
                if tag != "figure":
                    continue
                msrc = re.search(r'src="([^"]+)"', inner)
                if not msrc or msrc.group(1) == "cover.jpg":
                    continue
                n = notes.get(msrc.group(1)) or notes.get(Path(msrc.group(1)).name)
                if not n:
                    bad_corr.append(f"{msrc.group(1)}: 無描述條目")
                    continue
                ctx = [_TAG_RE.sub("", blocks[j][1]) for j in (i - 1, i + 1)
                       if 0 <= j < len(blocks) and blocks[j][0] != "figure"]
                s = _score(n, ctx)
                checked += 1
                if _verdict(s) == "fail":
                    bad_corr.append(f"{msrc.group(1)}: score={s:.3f} 與上下文不相關")
        results.append((
            "S6.11 圖文相關性(描述↔上下文)",
            not bad_corr,
            "; ".join(bad_corr[:4]) if bad_corr else f"{checked} 張圖皆 ≥ fail 門檻",
        ))

    # S6.6 dropcap 不套 **bold** 開頭
    bad_dropcap = []
    for p in pages:
        html = p.read_text(encoding="utf-8")
        if re.search(r'<p class="dropcap"><strong>', html):
            bad_dropcap.append(p.name)
    results.append((
        "S6.6 dropcap 不疊 <strong>",
        not bad_dropcap,
        f"found in: {bad_dropcap}" if bad_dropcap else f"all {len(pages)} pages OK",
    ))

    # S6.6 字面 ** 殘留(代表 markdown bold 沒被轉)
    bad_md = []
    for p in pages:
        html = p.read_text(encoding="utf-8")
        # 找 <p>...**...**</p> 內留下的字面 ** — 注意不能誤判 attr 內的 **
        # 簡化:body 內出現連續兩個 * 即抓
        if re.search(r"(?:<p[^>]*>|<h[23]>)[^<]*\*\*[^*]+\*\*", html):
            bad_md.append(p.name)
    results.append((
        "S6.6 markdown **bold** 已轉 <strong>",
        not bad_md,
        f"字面 ** 殘留於: {bad_md}" if bad_md else "no literal ** in body",
    ))

    return results


def _notes_match_slug(notes_path: Path, slug_dir: Path) -> bool:
    """image_notes.json 是否屬於這本書:看記錄的圖檔名與部署目錄的圖檔有交集。"""
    try:
        import json as _json
        files = {Path(n["file"]).name for n in _json.loads(notes_path.read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001 — 壞 JSON 視為不匹配即可
        return False
    deployed = {f.name for f in slug_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")}
    return len(files & deployed) >= max(1, len(files) // 2)


def audit_shelf_order(shelf: dict) -> list[tuple]:
    """S6.9 書架排序(2026-07-05 引入)— 新書一律 append 到 shelf.books 尾端,
    書脊往右長。非 placeholder 的 book.date(YYYY.MM.DD)必須**非遞減**(舊左新右)。
    date 是定寬點分式 → 字串比較即等於日期比較。SSoT: prompts/publish_qaqc.md § S6.9。
    """
    books = [b for b in shelf["books"] if not b.get("placeholder")]
    bad = []
    prev_id = prev_date = None
    for b in books:
        d = b.get("date")
        if d and prev_date and d < prev_date:
            bad.append(f"{b['id']}({d}) 排在 {prev_id}({prev_date}) 之後卻更早")
        if d:
            prev_id, prev_date = b["id"], d
    return [(
        "S6.9 書架排序(新書往右 append,date 非遞減)",
        not bad,
        "; ".join(bad) if bad else f"{len(books)} 本 date 遞增 ✓",
    )]


def audit_site_copy(pub_dir: Path) -> list[tuple]:
    """S6.7 Site copy freshness(safety net,不是 prevention)— grep
    app.jsx / data.js / index.html 內的紅旗詞,flag 給人工確認。

    ⚠️ 此檢查是『出版後 backstop』。真正的 prevention 應該在 Step 4.5
    (見 prompts/publish_qaqc.md § S4.5.9 文件家族同步清單)。Audit 抓到 ✗
    代表 S4.5.9 沒做好,應回頭把該文字改成 count-agnostic,而不是把紅旗詞
    從本函數移除。
    """
    results = []
    flags = ["預告階段", "各上線一本", "即將推出", "首本逐字稿", "尚未上線且", "還沒上線"]
    # SpineCard 內的「逐字稿尚未上線」是合法 placeholder fallback,允許保留 —
    # 故 "尚未上線" 不在預設紅旗詞,只比對更強的形式。
    for fname in ("app.jsx", "data.js", "index.html"):
        p = pub_dir / fname
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8")
        hits = []
        for flag in flags:
            for i, line in enumerate(txt.splitlines(), 1):
                if flag in line:
                    # SpineCard 內的 placeholder fallback 例外
                    if "placeholder" in line.lower() or "佔個位置" in line:
                        continue
                    hits.append(f"{fname}:{i} {flag!r}")
        results.append((
            f"S6.7 site copy 紅旗詞({fname})",
            not hits,
            f"找到 {len(hits)} 處,請人工確認:{hits[:3]}" if hits else "clean",
        ))
    return results


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Step 6 出版後 QAQC 自動審查")
    ap.add_argument("--slug", help="只審單一 slug")
    ap.add_argument("--quiet", action="store_true", help="只印失敗項目")
    args = ap.parse_args()

    data_js = PUB / "data.js"
    if not data_js.is_file():
        print(f"[ERROR] 找不到 {data_js}", file=sys.stderr)
        return 2

    try:
        shelves = parse_data_js(data_js)
    except Exception as e:
        print(f"[ERROR] data.js 解析失敗: {e}", file=sys.stderr)
        return 2

    total_pass = total_fail = total_books = 0

    # 跨書檢查:站台文字 freshness(S6.7)
    if not args.slug:  # --slug 模式跳過,避免無關書本被 flag
        print("\n=== Site copy freshness(S6.7,跨書) ===")
        for rule_id, ok, detail in audit_site_copy(PUB):
            if ok:
                total_pass += 1
                if not args.quiet:
                    print(f"  ✓ {rule_id} — {detail}")
            else:
                total_fail += 1
                print(f"  ✗ {rule_id} — {detail}")

    for shelf in shelves:
        shelf_id = shelf["id"]
        shelf_book_ids = [b["id"] for b in shelf["books"]]
        # S6.9 書架排序:全站模式逐架檢查;單 slug 模式只查該 slug 所屬書架
        if not args.slug or args.slug in shelf_book_ids:
            print(f"\n=== {shelf_id} 書架排序(S6.9) ===")
            for rule_id, ok, detail in audit_shelf_order(shelf):
                if ok:
                    total_pass += 1
                    if not args.quiet:
                        print(f"  ✓ {rule_id} — {detail}")
                else:
                    total_fail += 1
                    print(f"  ✗ {rule_id} — {detail}")
        for book in shelf["books"]:
            if book.get("placeholder"):
                continue
            if args.slug and book["id"] != args.slug:
                continue
            total_books += 1
            print(f"\n=== {book['id']} ({shelf_id}) — {book.get('title', '?')} ===")
            results = audit_book(book, shelf_id, PUB)
            for rule_id, ok, detail in results:
                if ok:
                    total_pass += 1
                    if not args.quiet:
                        print(f"  ✓ {rule_id}" + (f" — {detail}" if detail else ""))
                else:
                    total_fail += 1
                    print(f"  ✗ {rule_id}" + (f" — {detail}" if detail else ""))

    print("\n" + "=" * 60)
    print(f"審查完成:{total_books} 本書 / {total_pass} 項通過 / {total_fail} 項失敗")
    if total_fail == 0:
        print("✅ 全部通過")
        return 0
    print(f"❌ 有 {total_fail} 項失敗,見上方 ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
