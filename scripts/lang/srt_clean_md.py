#!/usr/bin/env python3
"""
srt_clean_md.py — 階段二:單一 SRT → 去時間軸、合併、通順的 cleaned.md(確定性,不用 LLM)。

實作 CLAUDE.md「整理」定義 + 零省略原則:
  - 去掉序號與時間軸
  - 丟掉:空白/純標點 cue、明顯雜訊(多語系亂碼、prompt 回放、全大寫拉丁尾巴)、--drop 指定的 cue
  - 合併破碎斷行 → 通順段落(依字數 + 句末標點換段)
  - 開頭插入一個講者標題(--title);不摘要、不改寫、不刪實質內容

用法:
  python3 srt_clean_md.py <in.srt> <out.md> --lang zh --title "## 講者…" [--drop 53,54,98]
"""
import sys, re, argparse
from pathlib import Path

PARA_MIN = 220
SENT_END = "。!?！?…」』）.\""

# 跨語系亂碼:中文場冒出韓/西里爾/泰文,通常是音樂/掌聲處的幻覺。
# 注意:刻意「不含」Latin-1 重音(À-ſ),因為 ä/é/ñ 是正常人名/外文借詞,不可誤殺(CLAUDE.md 原則 D1)。
_NONLOCAL = re.compile(r"[가-힣Ѐ-ӿ฀-๿]")  # 韓/西里爾/泰
_TRAIL_CAPS = re.compile(r"\s*(?:[A-Z]{2,}[\s,]+){1,}[A-Z]{2,}\s*$")        # 結尾全大寫拉丁串
_JUNK_LINE = re.compile(r"^(ke+y?\s+terms?\b|kee terms\b|br\.\.|※|請訂閱|字幕)", re.I)
# 英文幻覺片語(影片字幕殘留 / 靜音處):靠片語判斷,而非「整句是英文」——雙語場的真英文必須保留。
_HALL_EN = re.compile(r"^(thank(s| you) for watching|please subscribe|subscribe\b|the end\.?$|"
                      r"end of transcript|end credits|subtitles by|captions? by|transcription by)", re.I)


def parse_srt(text):
    out = []
    for blk in text.strip().split("\n\n"):
        ls = blk.split("\n")
        if len(ls) >= 3 and "-->" in ls[1]:
            out.append((int(ls[0]) if ls[0].isdigit() else len(out)+1, " ".join(ls[2:]).strip()))
    return out


def is_noise(text, lang):
    t = text.strip()
    if not t:
        return True
    if re.fullmatch(r"[。,、.,\s·…\-—~!?！?]*", t):    # 純標點/空白
        return True
    if _JUNK_LINE.match(t) or _HALL_EN.match(t) or "amara.org" in t.lower():
        return True
    if lang == "zh":
        # 跨語系亂碼:出現韓/西里爾/泰文(≥2 字)→ 多 script 幻覺
        if _NONLOCAL.search(t) and len(_NONLOCAL.findall(t)) >= 2:
            return True
        # 注意:不再因「整句是英文」就丟 —— 雙語場(主持人/講者 code-switch)的真英文必須保留(零省略)。
        #       英文的幻覺改由 _HALL_EN 片語表處理;漏網的語意幻覺交給 --drop(agent 判斷,見原則 6)。
    return False


def tidy(text, lang):
    t = text.strip()
    t = re.sub(r"^[。\.\s…—·,，、]+", "", t)          # 去開頭孤立標點(接縫)
    if lang == "zh":
        t = _TRAIL_CAPS.sub("", t).strip()            # 去結尾全大寫拉丁雜訊(MING PAO…)
        t = t.replace("Klaude", "Claude").replace("klaude", "Claude")
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_srt"); ap.add_argument("out_md")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--title", default="")
    ap.add_argument("--drop", default="")             # 逗號分隔的 cue 序號
    args = ap.parse_args()

    drop = {int(x) for x in args.drop.split(",") if x.strip().isdigit()}
    cues = parse_srt(Path(args.in_srt).read_text(encoding="utf-8"))

    kept_chars = 0
    dropped = 0
    paras, cur = [], ""
    sep = "" if args.lang == "zh" else " "
    for idx, text in cues:
        if idx in drop or is_noise(text, args.lang):
            dropped += 1
            continue
        t = tidy(text, args.lang)
        if not t:
            dropped += 1
            continue
        kept_chars += len(re.sub(r"\s", "", t))
        cur = (cur + sep + t).strip() if cur else t
        if len(re.sub(r"\s", "", cur)) >= PARA_MIN and cur[-1] in SENT_END:
            paras.append(cur); cur = ""
    if cur.strip():
        paras.append(cur.strip())

    md = []
    if args.title:
        md.append(args.title + "\n")
    md += [p + "\n" for p in paras]
    out = "\n".join(md).rstrip() + "\n"
    Path(args.out_md).write_text(out, encoding="utf-8")

    print(f"[clean] {args.in_srt}")
    print(f"        cue 總數 {len(cues)} | 丟棄(雜訊/指定){dropped} | 保留 {len(cues)-dropped}")
    print(f"        段落 {len(paras)} | 正文字數(去空白){kept_chars}")
    print(f"        → {args.out_md}")


if __name__ == "__main__":
    main()
