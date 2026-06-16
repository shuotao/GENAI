#!/usr/bin/env python3
"""
md_to_html.py — cleaned.md → 分頁式 HTML 逐字稿(致敬波隆納 transcript.html 質感)。

兩種輸出:
  預設(單頁 SPA):一個 .html,首頁卡片以 #session-N hash 切換視圖。
  --multipage <outdir>:輸出 index.html(封面 hero + 章節卡片→session-N.html)
      與每場各一頁 session-N.html;**每頁有自己的 OG 預覽圖(該場第一張圖,無圖則用封面)**。
      → 解法:hash #fragment 無法做「各章節各自的社群預覽」,必須每場獨立網址 + 各自 og:image。

圖片(Markdown):整行 ![](img) → 大圖;多張同行 → 並排;佔位 alt 抑制;字數 QAQC 排除圖片語法。
封面 --cover <img>:放在首頁「選擇章節」標題上方,並作為網頁(及無圖章節)的預設 OG 預覽圖。

用法:
  單頁  : md_to_html.py <md> <workdir> <out.html> [--cover IMG] [--base-url URL] [--tagline ..] [--footer ..]
  多頁  : md_to_html.py <md> <workdir> <outdir> --multipage --base-url https://goodedunote.web.app/<slug>/ [--cover IMG] ...
"""
import sys, json, re, html, argparse
from pathlib import Path

IMG_INLINE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_PLACEHOLDER_ALT = ("", "alt text", "alt", "image", "photo", "圖", "圖片")

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');
body { background:#fdfbf7; color:#2d2a26; font-family:'Noto Serif TC',serif; line-height:1.9; }
.ui { font-family:'Noto Sans TC',sans-serif; }
.view { display:none; }
.view.active { display:block; animation:fade .25s ease; }
@keyframes fade { from{opacity:0; transform:translateY(6px);} to{opacity:1; transform:none;} }
.prose h2 { color:#b34a2f; margin-top:2.5rem; border-left:5px solid #e0a892; padding-left:1rem; font-weight:700; }
.prose h3 { color:#c2683f; margin-top:2.25rem; font-weight:600; }
.prose p { margin-bottom:1.4rem; text-align:justify; }
.dropcap::first-letter { float:left; font-size:3.4rem; line-height:1; padding-right:.5rem; font-weight:700; color:#b34a2f; }
.chip { background:#b34a2f; color:#fff; font-variant-numeric:tabular-nums; }
.card { transition:.18s; }
.card:hover { background:#f6efe6; transform:translateY(-1px); box-shadow:0 6px 18px -10px rgba(120,60,40,.4); }
.btn { font-family:'Noto Sans TC',sans-serif; border:1px solid #e0c4b6; color:#b34a2f; border-radius:9999px; transition:.18s; }
.btn:hover { background:#b34a2f; color:#fff; border-color:#b34a2f; }
.hero { margin:1.5rem 0 2rem; }
.hero img { display:block; width:100%; height:auto; border-radius:16px; box-shadow:0 12px 32px -16px rgba(80,40,25,.55); }
.kc-fig { margin:1.8rem 0; text-align:center; }
.kc-fig img { display:block; max-width:100%; height:auto; margin:0 auto; border-radius:12px; box-shadow:0 8px 24px -14px rgba(80,40,25,.5); }
.kc-fig figcaption { margin-top:.6rem; font-size:.85rem; color:#9c8e82; }
.kc-inline { display:inline-block; max-width:100%; height:auto; border-radius:8px; vertical-align:middle; margin:.2rem; }
.kc-row { display:flex; flex-wrap:wrap; gap:.6rem; margin:1.8rem 0; }
.kc-row img { flex:1 1 0; min-width:140px; max-width:100%; height:auto; border-radius:12px; box-shadow:0 8px 24px -14px rgba(80,40,25,.5); object-fit:cover; }
html { scroll-behavior:smooth; }
</style>"""


def esc(s):
    return html.escape(s, quote=False)


def og_block(title, desc, image, url):
    m = [f'<meta property="og:type" content="article">',
         f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
         f'<meta name="twitter:card" content="summary_large_image">']
    if desc:  m.append(f'<meta property="og:description" content="{html.escape(desc, quote=True)}">')
    if url:   m.append(f'<meta property="og:url" content="{html.escape(url, quote=True)}">')
    if image: m += [f'<meta property="og:image" content="{html.escape(image, quote=True)}">',
                    f'<meta name="twitter:image" content="{html.escape(image, quote=True)}">']
    return "\n".join(m)


def head(title, og):
    return (f'<!DOCTYPE html>\n<html lang="zh-TW">\n<head>\n<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{esc(title)}</title>\n{og}\n<script src="https://cdn.tailwindcss.com"></script>\n{CSS}\n</head>\n')


def inline_md(text):
    """**bold** → <strong>。esc() 之後再呼叫。
    用 [^*]+ 限制不跨越下一個 *,避免吃進巢狀。"""
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)


def render_blocks(lines_iter, first_in_sec_start=True):
    """把段落/圖片 lines 轉成 article 內 HTML;回傳 (blocks_html_list, para_chars, first_img_src)。"""
    blocks, para_chars, first_img, first_in = [], 0, None, first_in_sec_start
    for s in lines_iter:
        if s.startswith("### "):
            blocks.append(f'      <h3>{inline_md(esc(s[4:].strip()))}</h3>'); continue
        imgs = IMG_INLINE.findall(s)
        remainder = re.sub(r"[·、,，.\s]+", "", IMG_INLINE.sub("", s))
        if imgs and remainder == "":
            if first_img is None: first_img = imgs[0][1]
            if len(imgs) == 1:
                alt, src = imgs[0]
                cap = "" if alt.strip().lower() in _PLACEHOLDER_ALT else f'<figcaption>{esc(alt.strip())}</figcaption>'
                blocks.append(f'      <figure class="kc-fig"><img src="{src}" alt="{esc(alt)}" loading="lazy">{cap}</figure>')
            else:
                cells = "".join(f'<img src="{src}" alt="{esc(alt)}" loading="lazy">' for alt, src in imgs)
                blocks.append(f'      <div class="kc-row">{cells}</div>')
            continue
        # 若段落以 **bold** 開頭(speaker label,例如 Q&A 的 **Q(主持人)**:...),
        # 跳過 dropcap — 否則 ::first-letter 會把 * 也吃進去,放大成怪相
        use_dropcap = first_in and not s.lstrip().startswith("**")
        cls = ' class="dropcap"' if use_dropcap else ""
        first_in = False
        txt = IMG_INLINE.sub(lambda m: f'<img class="kc-inline" src="{m.group(2)}" alt="{esc(m.group(1))}" loading="lazy">', esc(s))
        txt = inline_md(txt)
        blocks.append(f"      <p{cls}>{txt}</p>")
        para_chars += len(re.sub(r"\s", "", IMG_INLINE.sub("", s)))
    return blocks, para_chars, first_img


def parse(md_path):
    lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    h1, subtitle, sessions, cur = "完整逐字稿", "", [], None
    preamble = []
    for ln in lines:
        s = ln.rstrip()
        if not s.strip(): continue
        if s.startswith("# ") and not s.startswith("## "): h1 = s[2:].strip(); continue
        if s.startswith("*") and s.endswith("*") and len(s) > 2 and not subtitle: subtitle = s.strip("*").strip(); continue
        if s.startswith("## "): cur = {"title": s[3:].strip(), "lines": []}; sessions.append(cur); continue
        # 第一個 ## 之前的正文(來源/方法前言)= front-matter,不另成章節,
        # 否則會多生一個空標題 session,讓章節數比 toc 多一頁、index 連結錯位。
        if cur is None: preamble.append(s); continue
        cur["lines"].append(s)
    if not sessions and preamble:  # 整份沒有任何 ## → 全文當單一章節(單頁 fallback,行為不變)
        sessions.append({"title": "", "lines": preamble})
    return h1, subtitle, sessions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md"); ap.add_argument("workdir"); ap.add_argument("out")
    ap.add_argument("--tagline", default="完整逐字稿 · 零省略")
    ap.add_argument("--footer", default="完整逐字稿排版存檔 · 零省略,全程無摘要。")
    ap.add_argument("--cover", default="")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--multipage", action="store_true")
    ap.add_argument("--back-anchor", default="shelves",
                    help="回到時要 scroll 到的 anchor(預設 shelves);讀書會書用 shelf-reading,公開活動用 shelf-public,研討會用 shelf-seminar")
    ap.add_argument("--back-label", default="書架",
                    help="回到按鈕的文字(會帶『← 回到』前綴);例如:讀書會書架、公開活動書架、研討會書架")
    a = ap.parse_args()

    h1, subtitle, sessions = parse(a.md)
    toc = json.loads(Path(a.workdir, "toc.json").read_text(encoding="utf-8"))
    n = len(sessions)
    base = a.base_url.rstrip("/") + "/" if a.base_url else ""
    cover_abs = (base + a.cover) if (a.cover and base) else (a.cover or "")

    # 預先算每場 blocks + 第一張圖
    built = []
    total_chars = 0
    for sess in sessions:
        blocks, pc, fimg = render_blocks(sess["lines"])
        total_chars += pc
        built.append({"blocks": blocks, "first_img": fimg})

    def hero_html():
        return (f'  <div class="hero"><img src="{a.cover}" alt="{esc(h1)}"></div>\n' if a.cover else "")

    def header_html():
        return (f'  <header class="mb-6 text-center">\n'
                f'    <h1 class="text-3xl md:text-4xl font-bold mb-3">{esc(h1)}</h1>\n'
                f'    <p class="text-stone-500 italic">{esc(subtitle)}</p>\n'
                f'    <div class="ui mt-5 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs font-bold text-stone-400 tracking-widest uppercase">\n'
                f'      <span>{total_chars:,} 字逐字稿</span><span>•</span><span>{n} 個章節</span><span>•</span><span>{esc(a.tagline)}</span>\n'
                f'    </div>\n  </header>\n')

    def cards_html(href_fn):
        out = []
        for i, r in enumerate(toc):
            out.append(
                f'      <a href="{href_fn(i+1)}" class="card block rounded-xl border border-stone-200 bg-white/60 p-4 flex gap-4 items-start no-underline">'
                f'<span class="chip ui text-xs rounded px-2 py-1 mt-0.5 whitespace-nowrap">{esc(r.get("time",""))}</span>'
                f'<span class="flex-1"><span class="block font-bold text-stone-700 text-lg">{esc(r["talk"])}</span>'
                f'<span class="ui block text-sm text-stone-500 mt-0.5">{esc(r.get("speakers",""))}</span></span>'
                f'<span class="ui text-stone-300 text-2xl leading-none mt-1">›</span></a>')
        return "\n".join(out)

    def chapters_section(href_fn):
        return (f'{hero_html()}'
                f'    <h2 class="ui text-sm font-bold tracking-widest text-stone-400 uppercase mb-4">選擇章節 · Chapters</h2>\n'
                f'    <div class="space-y-3">\n{cards_html(href_fn)}\n    </div>\n')

    def session_meta(i):
        return toc[i] if i < len(toc) else {"time": "", "talk": sessions[i]["title"], "speakers": ""}

    def session_head_block(i):
        m = session_meta(i)
        return (f'      <div class="ui mb-6 pb-5 border-b border-stone-200">'
                f'<span class="chip text-xs rounded px-2 py-1">{esc(m.get("time",""))}</span>'
                f'<h2 class="text-2xl font-bold text-stone-800 mt-3" style="border:0;padding:0;margin-top:.75rem;">{esc(m["talk"])}</h2>'
                f'<p class="text-sm text-stone-500 mt-1">{esc(m.get("speakers",""))}</p></div>')

    # 統一授權聲明(雙軌:程式碼 MIT / 內容 CC BY 4.0 / 講者話語講者保留)
    # 細節見 NOTICE 與 LICENSE-CONTENT
    license_line = ('<p class="mt-3 text-xs" style="color:#a8a094;letter-spacing:0.04em;">'
                    '程式碼 MIT · 站台文案與筆記 '
                    '<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer" '
                    'style="border-bottom:1px solid currentColor;">CC BY 4.0</a>'
                    ' · 講者話語著作權歸各場講者個人'
                    '</p>')
    footer = (f'  <footer class="ui mt-20 pt-10 border-t border-stone-200 text-center text-stone-400 text-sm">'
              f'<p>{esc(a.footer)}</p>{license_line}</footer>\n')

    # 回到該書所屬書架那一段(不是 hero,也不是不分書架的整個圖書館)
    back_href = f"../#{a.back_anchor}" if a.back_anchor else "../"
    back_text = f"← 回到{a.back_label}"
    lib_btn = (f'      <a href="{back_href}" class="btn ui inline-flex items-center px-3 py-1 text-xs" '
               f'style="color:#9a8678;border-color:#d4c0b3;">{esc(back_text)}</a>\n')
    session_top_bar = ('      <div class="flex items-center gap-3 mb-8">\n'
                       f'{lib_btn}'
                       '        <a href="index.html" class="btn ui inline-flex items-center px-4 py-2 text-sm">← 回到選擇</a>\n'
                       '      </div>\n')

    if not a.multipage:
        # ── 單頁 SPA ──
        og = og_block(h1, subtitle, cover_abs, base or "")
        parts = [head(h1, og), '<body>\n<div class="max-w-3xl mx-auto px-6 py-12" id="top">\n']
        parts.append(f'  <section class="view" id="home">\n'
                     f'      <div class="mb-6">{lib_btn}      </div>\n'
                     f'{header_html()}{chapters_section(lambda i: f"#session-{i}")}'
                     f'    <p class="ui text-xs text-stone-400 mt-6 text-center">點任一章節進入完整逐字內容。</p>\n  </section>\n')
        for i, b in enumerate(built):
            nxt = (f'      <a href="#session-{i+2}" class="btn ui px-4 py-2 text-sm">下一個:{esc(session_meta(i+1)["talk"])} →</a>' if i+1 < n else "")
            parts.append(
                f'  <section class="view" id="session-{i+1}">\n'
                f'      <div class="flex items-center gap-3 mb-8">\n{lib_btn}'
                f'        <a href="#home" class="btn ui inline-flex items-center px-4 py-2 text-sm">← 回到選擇</a>\n      </div>\n'
                f'{session_head_block(i)}\n    <article class="prose prose-stone mx-auto">\n' + "\n".join(b["blocks"]) +
                f'\n    </article>\n    <div class="mt-12 pt-8 border-t border-stone-200 flex flex-wrap gap-3 justify-between items-center">\n'
                f'      <a href="#home" class="btn ui inline-flex items-center px-4 py-2 text-sm">← 回到選擇</a>\n{nxt}\n    </div>\n  </section>\n')
        parts.append(footer + '</div>\n<script>\nfunction sv(id){var v=document.querySelectorAll(".view");var t=document.getElementById(id)||document.getElementById("home");v.forEach(function(x){x.classList.remove("active")});t.classList.add("active");window.scrollTo(0,0);}\nfunction r(){sv((location.hash||"#home").slice(1));}\naddEventListener("hashchange",r);addEventListener("DOMContentLoaded",r);\n</script>\n</body>\n</html>\n')
        Path(a.out).write_text("".join(parts), encoding="utf-8")
        out_desc = a.out
    else:
        # ── 多頁:index + 每場一頁,各自 OG ──
        outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
        # index.html
        og = og_block(h1, subtitle, cover_abs, base or "")
        idx = [head(h1, og), '<body>\n<div class="max-w-3xl mx-auto px-6 py-12">\n',
               f'      <div class="mb-6">{lib_btn}      </div>\n',
               header_html(),
               chapters_section(lambda i: f"session-{i}.html"),
               '    <p class="ui text-xs text-stone-400 mt-6 text-center">點任一章節進入完整逐字內容。</p>\n', footer, '</div>\n</body>\n</html>\n']
        (outdir / "index.html").write_text("".join(idx), encoding="utf-8")
        # 每場一頁
        for i, b in enumerate(built):
            m = session_meta(i)
            og_img = (base + b["first_img"]) if (b["first_img"] and base) else cover_abs
            og = og_block(f'{h1} — {m["talk"]}', m.get("speakers", "") or subtitle, og_img, (base + f"session-{i+1}.html") if base else "")
            nxt = (f'      <a href="session-{i+2}.html" class="btn ui px-4 py-2 text-sm">下一個:{esc(session_meta(i+1)["talk"])} →</a>' if i+1 < n else "")
            page = [head(f'{h1} — {m["talk"]}', og), '<body>\n<div class="max-w-3xl mx-auto px-6 py-12">\n',
                    session_top_bar,
                    session_head_block(i), '\n    <article class="prose prose-stone mx-auto">\n', "\n".join(b["blocks"]),
                    '\n    </article>\n    <div class="mt-12 pt-8 border-t border-stone-200 flex flex-wrap gap-3 justify-between items-center">\n'
                    '      <a href="index.html" class="btn ui inline-flex items-center px-4 py-2 text-sm">← 回到選擇</a>\n', nxt, '\n    </div>\n',
                    footer, '</div>\n</body>\n</html>\n']
            (outdir / f"session-{i+1}.html").write_text("".join(page), encoding="utf-8")
        out_desc = f"{outdir}/(index + session-1..{n}).html"

    # QAQC
    md_lines = Path(a.md).read_text(encoding="utf-8").splitlines()
    md_body = "".join(IMG_INLINE.sub("", l) for l in md_lines if l.strip() and not l.startswith("#") and not (l.startswith("*") and l.rstrip().endswith("*")))
    md_chars = len(re.sub(r"\s", "", md_body))
    print(f"[html] 模式={'多頁' if a.multipage else '單頁'} | 章節 {n} | 封面={a.cover or '無'} | 段落字數(去圖){total_chars} | md 正文 {md_chars} | 保留率 {total_chars/max(1,md_chars):.4%}")
    print(f"[html] → {out_desc}")


if __name__ == "__main__":
    main()
