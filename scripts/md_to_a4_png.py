#!/usr/bin/env python3
"""
scripts/md_to_a4_png.py — 把 markdown 確定性渲染成 A4 白底 PNG(多頁),可選疊「好學生筆記」註解。

兩種用途:
  1) 純底圖(base):md → A4 白底 PNG,文字真 DOM 渲染 → 原文零遺漏。
  2) 疊註解(連續圖說的成品):再吃一份「註解 JSON」,用**決定性 CSS/SVG**把
     藍圈/黃螢光/紅!?/便利貼/💡洞察疊到各自 anchor 所在的頁面上 → 每頁=它自己的內容、
     風格 100% 一致(同一套 CSS)、原文一字不改。**不靠影像模型,沒有選錯圖/重畫的風險。**

A4 版面、字體、註解 CSS 對齊 web/studio.html + web/studio.js:applyAnnotationsToDom。

依賴:Playwright(headless Chromium)
    pip install playwright && playwright install chromium

用法:
    python3 scripts/md_to_a4_png.py <input.md> <out_dir> [--prefix base]
    python3 scripts/md_to_a4_png.py <input.md> <out_dir> [--prefix p] [--annotations ann.json]
"""

import argparse
import json
import sys
from pathlib import Path

# A4 @ 96dpi(與 web/studio.js:buildA4Host 一致)
A4_W = 794
A4_H = 1123
SCALE = 2  # ≈150 DPI

# 註解規則的 6 色 CSS(對齊 web/studio.html);手寫字體 Long Cang。
# 用 token 佔位 + str.replace 填值(CSS 含 % 與 {},不能用 %-format / .format)。
_HTML_TEMPLATE = r"""<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700&family=Long+Cang&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#ffffff; }
  #page {
    width: __W__px; background:#ffffff; color:#333; position:relative;
    padding: 56px; box-sizing:border-box;
    font-family:'Noto Sans TC',sans-serif; font-size:16px; line-height:1.85;
  }
  #page h1,#page h2,#page h3 { color:#1a1a1a; margin:1.1em 0 .5em; }
  #page h1 { font-size:1.5rem; } #page h2 { font-size:1.25rem; } #page h3 { font-size:1.08rem; }
  #page p { margin:.6em 0; } #page ul,#page ol { padding-left:1.5em; margin:.5em 0; }
  #page blockquote { border-left:3px solid #5a5; margin:1em 0; padding:6px 12px; background:#f3f8f3; color:#444; }
  #page code { background:#eee; padding:1px 5px; border-radius:3px; }
  /* 註解類別(對齊 web/studio.html) */
  .hl-yellow { background: linear-gradient(transparent 55%, rgba(255,235,59,0.65) 55%); padding:0 1px; }
  .kw-blue { color:#1976D2; font-weight:700; border-bottom:2px solid #1976D2; }
  .mark-red { color:#D32F2F; font-weight:700; font-family:'Long Cang','Noto Sans TC',cursive; margin-left:2px; }
  .postit-orange, .postit-green {
    font-family:'Long Cang','Noto Sans TC',cursive; font-size:1.12em; line-height:1.5;
    padding:8px 12px; margin:8px 0 10px 28px; border-radius:4px; display:block;
  }
  .postit-orange { background:#FFF3E0; border-left:4px solid #E65100; color:#E65100; }
  .postit-green  { background:#E8F5E9; border-left:4px solid #388E3C; color:#2E7D32; }
  .insight-box {
    font-family:'Long Cang','Noto Sans TC',cursive; font-size:1.18em; line-height:1.5;
    margin-top:22px; padding:12px 16px; background:#FFEBEE; border:2px dashed #D32F2F;
    border-radius:6px; color:#C62828;
  }
</style></head>
<body><div id="page"></div>
<script>
  const MD = __MD_JSON__;
  const ANN = __ANN_JSON__;  // null 或 {highlights,keyterms,marks,sidenotes,insight}
  const page = document.getElementById('page');
  page.innerHTML = marked.parse(MD);

  function wrapFirstMatch(root, phrase, cls) {
    if (!phrase || phrase.length < 2) return false;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (n.parentElement && n.parentElement.closest('.postit-orange,.postit-green,.insight-box,.kw-blue,.hl-yellow')) continue;
      const i = n.textContent.indexOf(phrase);
      if (i < 0) continue;
      const before = n.textContent.slice(0, i), after = n.textContent.slice(i + phrase.length);
      const s = document.createElement('span'); s.className = cls; s.textContent = n.textContent.slice(i, i + phrase.length);
      const frag = document.createDocumentFragment();
      if (before) frag.appendChild(document.createTextNode(before));
      frag.appendChild(s);
      if (after) frag.appendChild(document.createTextNode(after));
      n.parentNode.replaceChild(frag, n);
      return true;
    }
    return false;
  }
  function findBlock(root, phrase) {
    if (!phrase) return null;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (n.textContent.includes(phrase)) return n.parentElement && (n.parentElement.closest('p,li,h1,h2,h3,blockquote') || n.parentElement);
    }
    return null;
  }
  if (ANN) {
    (ANN.keyterms || []).forEach(t => wrapFirstMatch(page, String(t).trim(), 'kw-blue'));
    (ANN.highlights || []).forEach(h => wrapFirstMatch(page, String(h).trim(), 'hl-yellow'));
    (ANN.marks || []).forEach(m => {
      const b = findBlock(page, ((m && m.anchor) || '').trim());
      if (!b) return;
      const s = document.createElement('span'); s.className = 'mark-red';
      s.textContent = ' ' + (m.kind === 'question' ? '?' : '!') + (m.text ? ' ' + m.text : '');
      b.appendChild(s);
    });
    (ANN.sidenotes || []).forEach(sd => {
      const b = findBlock(page, ((sd && sd.anchor) || '').trim());
      const d = document.createElement('div');
      d.className = (sd && sd.color === 'green') ? 'postit-green' : 'postit-orange';
      d.textContent = (sd && sd.text) || '';
      if (b && b.parentNode) b.parentNode.insertBefore(d, b.nextSibling); else page.appendChild(d);
    });
    if (ANN.insight) {
      const box = document.createElement('div'); box.className = 'insight-box';
      box.textContent = '💡 核心洞察:' + ANN.insight;
      page.appendChild(box);
    }
  }
  window.__ready = false;
  (async () => { try { await document.fonts.ready; } catch (e) {} window.__ready = true; })();
</script></body></html>"""


def _build_html(md_text: str, annotations: dict | None) -> str:
    return (_HTML_TEMPLATE
            .replace("__W__", str(A4_W))
            .replace("__MD_JSON__", json.dumps(md_text, ensure_ascii=False))
            .replace("__ANN_JSON__", json.dumps(annotations, ensure_ascii=False) if annotations else "null"))


def render_md_to_a4(md_path: Path, out_dir: Path, prefix: str = "base",
                    annotations: dict | None = None, collect_text: bool = False):
    """Render markdown → A4 PNG pages. With `annotations`, overlay 好學生筆記 註解(決定性)。
    collect_text=True → 回 (files, page_texts):每頁實際落在該頁的文字(讓 banana 知道每頁的內容,
    避免重複畫第 1 頁)。否則回 files(list[Path])。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("[md_to_a4_png] 缺 Playwright。請先:pip install playwright && playwright install chromium")

    md_text = Path(md_path).read_text(encoding="utf-8")
    html = _build_html(md_text, annotations)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": A4_W, "height": A4_H}, device_scale_factor=SCALE)
        page.set_content(html, wait_until="networkidle")
        page.wait_for_function("window.__ready === true", timeout=15000)
        total_h = page.evaluate("document.getElementById('page').scrollHeight")
        n_pages = max(1, -(-total_h // A4_H))  # ceil
        page.evaluate(f"document.getElementById('page').style.minHeight = '{n_pages * A4_H}px';")
        page.set_viewport_size({"width": A4_W, "height": n_pages * A4_H})
        for i in range(n_pages):
            fp = out_dir / f"{prefix}_p{i + 1:02d}.png" if prefix != "p" else out_dir / f"p{i + 1:02d}.png"
            page.screenshot(path=str(fp), clip={"x": 0, "y": i * A4_H, "width": A4_W, "height": A4_H})
            files.append(fp)
        page_texts = None
        if collect_text:
            # 把每個區塊依其 offsetTop 分到所屬頁 → 得到「每一頁的實際文字」。
            page_texts = page.evaluate(
                "(A4H) => {"
                "  const b = {};"
                "  document.querySelectorAll('#page h1,#page h2,#page h3,#page p,#page li,#page blockquote')"
                "    .forEach(el => { const pg = Math.floor(el.offsetTop / A4H);"
                "      (b[pg] = b[pg] || []).push((el.innerText||'').trim()); });"
                "  const out = []; for (let i=0;i<" + str(n_pages) + ";i++) out.push((b[i]||[]).join('\\n'));"
                "  return out;"
                "}", A4_H)
        browser.close()
    return (files, page_texts) if collect_text else files


def main():
    ap = argparse.ArgumentParser(description="Render markdown to A4 PNG pages (+optional notes overlay)")
    ap.add_argument("input_md")
    ap.add_argument("out_dir")
    ap.add_argument("--prefix", default="base", help="檔名前綴;'p' → 直接 p01.png(成品)")
    ap.add_argument("--annotations", default=None, help="註解 JSON 檔(疊好學生筆記)")
    args = ap.parse_args()
    ann = json.loads(Path(args.annotations).read_text(encoding="utf-8")) if args.annotations else None
    files = render_md_to_a4(Path(args.input_md), Path(args.out_dir), args.prefix, ann)
    print(json.dumps({"pages": len(files), "files": [str(f) for f in files]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
