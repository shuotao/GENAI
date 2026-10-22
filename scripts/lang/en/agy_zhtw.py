#!/usr/bin/env python3
"""
agy_zhtw.py — 英文 cleaned.raw.md → 繁中 cleaned.md(忠實翻譯 + 校稿),走 Antigravity headless。

為什麼是 agy:`agy -p`(= `antigravity -p`)走 Antigravity 自己的 OAuth login,
屬合法 CLI 授權通道(CLAUDE.md 原則 5 Auth 雙軌表);不碰 GEMINI_API_KEY。
為什麼可以「翻譯+校稿」一次做:cleaned.md 本來就丟棄時間軸(Gotcha #6 例外條款),
零省略改以 **段落 1:1 對齊(E3)** 驗證,不用跨語言失效的字數比。

流程(確定性外殼,LLM 只做翻譯判斷 — 原則 6):
  1. 讀 in_md,依空行切段 → [P001]…[Pnnn] 標籤
  2. 分批(--batch)送 `agy -p --model <m>`;每段可選擇在標籤後加一行 `## 標題`
  3. 解析回傳,段數/標籤不齊 → 該批重試一次,仍不齊即 exit 2(不寫半成品)
  4. 寫 out_md(標題 + 段落),原始回應存 <out>.agy_raw.txt 供稽核

用法:
  python3 agy_zhtw.py <in.md> <out.md> [--model gemini-3.8-flash-medium]
                      [--context sessions/<slug>/context.txt] [--batch 30] [--title "# …"]
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "gemini-3.8-flash-medium"

PROMPT = """你是專業口譯稿譯者。以下是一段英文錄音的逐字稿(Whisper 轉錄,口語、文法可能破碎),
共 {n} 段,每段以 [Pnnn] 標籤開頭。請「忠實翻譯」成台灣繁體中文(zh-TW),規則:
1. 零省略:每一句都要翻,不得摘要、濃縮、改寫成第三人稱;保留第一人稱與口語感(you know / um 這類純贅字可去)。
2. 標籤 1:1:輸出恰好 {n} 個 [Pnnn] 區塊,以原本標籤開頭、順序不變。區塊內可依語意再分段
   (段間空一行),目標每段 60~120 字、寧短勿長,一個語意單元(論點/舉例/對話)= 一段。
3. 標題(可選):若某段開啟新話題,可在該段標籤的「下一行」寫一行 `## 標題`(不超過 20 字),再接譯文;
   標題只能插在段落之前,不能取代原文。除此之外不要輸出任何說明文字。
4. 用全形標點(,。?!、:「」)。台灣用語(資料中心、軟體、專案…)。
5. 專名:人名/公司/產品維持原文或通行譯名,第一次出現可用「中文(English)」;ASR 明顯誤聽且能確定者直接校正。
6. 聽不懂或明顯破碎處照字面直譯,不要腦補。
{glossary}
{body}
"""


def find_agy() -> str | None:
    return shutil.which("agy") or shutil.which("antigravity")


def split_paras(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.lstrip().startswith("#")]


def parse(raw: str, ids: list[int]) -> dict[int, tuple[str | None, str]] | None:
    segs = re.split(r"^\s*\[P(\d{3})\]\s*", raw, flags=re.M)
    got = {}
    for i in range(1, len(segs) - 1, 2):
        lines = segs[i + 1].strip().splitlines()
        heading = None
        if lines and lines[0].lstrip().startswith("#"):
            heading = "## " + lines[0].lstrip("# ").strip()
            lines = lines[1:]
        # 區塊內空行 = 譯者依 R2.1 再分段;非空行接回同段
        text = re.sub(r"\n\s*\n", "\n\n", "\n".join(l.strip() for l in lines)).strip()
        text = "\n\n".join(" ".join(p.split("\n")) for p in text.split("\n\n"))
        got[int(segs[i])] = (heading, text)
    if sorted(got) != ids or any(not t for _, t in got.values()):
        return None
    return got


def cjk_len(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def short_blocks(batch, got, min_ratio) -> list[int]:
    """零省略量化守門:每塊「譯文 CJK 字 / 原文英文詞」低於 min_ratio 視為疑似漏譯。
    短塊(<20 詞,如 Okay. Yeah.)比例天生不穩,不判。"""
    bad = []
    for i, p in batch:
        words = len(p.split())
        if words >= 20 and cjk_len(got[i][1]) < min_ratio * words:
            bad.append(i)
    return bad


def run_batch(agy: str, model: str, glossary: str, batch: list[tuple[int, str]], log,
              min_ratio: float) -> dict:
    body = "\n\n".join(f"[P{i:03d}] {p}" for i, p in batch)
    prompt = PROMPT.format(n=len(batch), glossary=glossary, body=body)
    ids = [i for i, _ in batch]
    span = f"P{ids[0]:03d}-P{ids[-1]:03d}"
    for attempt in (1, 2, 3):
        r = subprocess.run([agy, "-p", prompt, "--model", model, "--disable-slash-commands"],
                           capture_output=True, text=True, encoding="utf-8", timeout=1200)
        log.write(f"=== {span} attempt {attempt} rc={r.returncode} ===\n"
                  f"{r.stdout}\n--- stderr ---\n{r.stderr}\n")
        got = parse(r.stdout, ids)
        if not got:
            print(f"[agy-zhtw] {span} 對齊失敗(attempt {attempt})", file=sys.stderr)
            continue
        bad = short_blocks(batch, got, min_ratio)
        if not bad:
            return got
        print(f"[agy-zhtw] {span} 疑似漏譯 {['P%03d' % b for b in bad]}"
              f"(CJK/詞 < {min_ratio},attempt {attempt})", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="EN cleaned.raw.md → zh-TW cleaned.md via agy headless")
    ap.add_argument("in_md")
    ap.add_argument("out_md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--context", help="session context.txt(講者/公司/專名),當翻譯專名表")
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--title", default="")
    ap.add_argument("--min-ratio", type=float, default=0.9,
                    help="每塊譯文 CJK 字 / 原文英文詞 下限(零省略守門;口語英文正常約 1.1~1.4)")
    args = ap.parse_args()

    agy = find_agy()
    if not agy:
        print("[agy-zhtw] 找不到 agy / antigravity CLI", file=sys.stderr)
        sys.exit(3)

    paras = split_paras(Path(args.in_md).read_text(encoding="utf-8"))
    ctx = Path(args.context).read_text(encoding="utf-8").strip() if args.context and Path(args.context).exists() else ""
    glossary = f"7. 本次背景/專名(以此為準):{ctx}\n" if ctx else ""

    out = Path(args.out_md)
    numbered = list(enumerate(paras, 1))
    result = {}
    with open(out.with_suffix(".agy_raw.txt"), "w", encoding="utf-8") as log:
        for k in range(0, len(numbered), args.batch):
            batch = numbered[k:k + args.batch]
            print(f"[agy-zhtw] P{batch[0][0]:03d}-P{batch[-1][0]:03d} / {len(paras)} ({args.model})")
            result.update(run_batch(agy, args.model, glossary, batch, log, args.min_ratio))

    lines = [args.title, ""] if args.title else []
    for i in range(1, len(paras) + 1):
        heading, text = result[i]
        if heading:
            lines += [heading, ""]
        lines += [text, ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    cjk = cjk_len("\n".join(t for _, t in result.values()))
    words = sum(len(p.split()) for p in paras)
    print(f"[agy-zhtw] OK 區塊 {len(paras)}=={len(result)}(E3 1:1),"
          f"CJK {cjk} 字 / 英文 {words} 詞 = {cjk / max(1, words):.2f} → {out}")


if __name__ == "__main__":
    main()
