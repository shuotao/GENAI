#!/usr/bin/env python3
"""placement_check.py — 圖片「分佈塌陷」確定性檢核(§ S4.5.11 / § S6.11)。

動機(2026-07-09):propose_anchors 舊 DP 只求總分最大、對「多張圖疊同一段落」零成本,
造成整段 demo 的截圖一口氣倒在一個 anchor(實例:day2 第8場 12 張擠一行)。相關性
gate 是「逐張看局部分數」→ 每張單看都過,整份 audit 綠,塌陷被放行。本模組補上
gate/audit 從來沒有的那層:**分佈檢核**——單一 anchor 掛超過 max_per_anchor 張即判失敗。

「anchor」定義:md 是逐行段落模型(md_to_html 每個非空行 = 一個 <p>/<h*>)。一段
連續的圖片行都掛在其前面最近的正文行上 = 同一 anchor。連續 t 張 = 該 anchor 疊 t 張。

近重複頁(章節卡模板、連拍幀)合理會疊 2 張,故預設門檻 max_per_anchor=2(3 張起 fail)。
"""
from __future__ import annotations
import re

IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")   # 一行可含多張(kc-row 並排,F1)
_CJK = re.compile(r"[一-鿿㐀-䶿]")
_ASCII_WORD = re.compile(r"[A-Za-z]{2,}")
DEFAULT_MAX_PER_ANCHOR = 2


def _is_local_img(ref: str) -> bool:
    return not ref.startswith("http") and ref != "cover.jpg"


def _is_substantial(text: str) -> bool:
    """夠格當 anchor / 打斷 run 的正文行:至少一個 CJK 字、ASCII 詞或多位數字。
    純標點/單字元墊行(F4)不算 → 不會被用來把塌陷切成假的小 run。"""
    return bool(_CJK.search(text) or _ASCII_WORD.search(text) or re.search(r"\d{2,}", text))


def anchor_runs(md_text: str) -> list[tuple[str, list[str]]]:
    """回傳 [(anchor 正文行, [連續掛此 anchor 的本地圖 ref...]), ...]。

    F1:一行多張(kc-row 並排)全部計入同一 run。
    F3:非本地圖(http / cover.jpg)透明跳過,不重置 run、不當 anchor。
    F4:純標點/單字元墊行不打斷 run(避免用一字墊行偽裝分散)。
    """
    lines = [ln for ln in md_text.splitlines() if ln.strip()]
    runs: list[tuple[str, list[str]]] = []
    last_content = ""
    cur: list[str] | None = None
    for ln in lines:
        refs = IMG_REF.findall(ln)
        local = [r for r in refs if _is_local_img(r)]
        remainder = IMG_REF.sub("", ln).strip()  # 去掉圖語法後剩下的文字
        if local:                                 # 圖片行(可能一行多張)→ 累積,不重置
            if cur is None:
                cur = []
                runs.append((last_content, cur))
            cur.extend(local)
        elif refs and not _is_substantial(remainder):
            continue                              # 只有非本地圖(cover/http)→ 透明跳過
        elif _is_substantial(remainder):          # 實質正文行 → 打斷 run、更新 anchor
            last_content = remainder
            cur = None
        # 其餘(純標點/墊行)→ 什麼都不做,不打斷 run
    return runs


def overstacked(md_text: str, max_per_anchor: int = DEFAULT_MAX_PER_ANCHOR,
                approved: set | None = None) -> list[tuple[str, list[str]]]:
    """回傳超過門檻的 anchor 組:[(anchor 文字, [refs...]), ...]。

    approved:人工確認可連放的圖 basename 集合;若一組塌陷的圖**全部**在 approved 內
    (人工刻意分組),則不列入(§ S4.5.11 人工覆寫)。"""
    approved = approved or set()

    def _base(r):
        return r.split("/")[-1]
    out = []
    for a, refs in anchor_runs(md_text):
        if len(refs) <= max_per_anchor:
            continue
        if all(_base(r) in approved for r in refs):
            continue                      # 整組人工確認 → 放行
        out.append((a, refs))
    return out


_SEQ_RE = re.compile(r"(\d{2,})\.\w+$")   # 副檔名前的序號 ≥2 位(含 01.png / happy-01.png / -0232.png)


def _seq_of(ref: str, deck_page_of: dict | None) -> int | None:
    """圖片的原始順序鍵:優先用 image_notes 的 deck_page,否則用檔名序號 `-NNNN.png`。"""
    if deck_page_of:
        dp = deck_page_of.get(ref) or deck_page_of.get(ref.split("/")[-1])
        if dp is not None:
            return dp
    m = _SEQ_RE.search(ref)
    return int(m.group(1)) if m else None


def order_inversions(md_text: str, deck_page_of: dict | None = None
                     ) -> list[tuple[str, int, str, int]]:
    """回傳「文件順序」中原始順序逆位的相鄰對 [(前ref, 前序, 後ref, 後序), ...]。

    投影片截圖有固有先後(deck_page / 檔名序號)。插圖後文件裡的圖序若出現「後面的
    投影片被排到前面」= 與講者原始放映順序錯位(§ S4.5.11)。單調 DP 本應防止,但手動
    編輯/複核可能破壞 → 這是把「不得錯位」變成可稽核的硬檢核。
    """
    seq = []
    for ln in md_text.splitlines():
        for ref in IMG_REF.findall(ln):
            if _is_local_img(ref):
                s = _seq_of(ref, deck_page_of)
                if s is not None:
                    seq.append((ref, s))
    return [(seq[i][0], seq[i][1], seq[i + 1][0], seq[i + 1][1])
            for i in range(len(seq) - 1) if seq[i + 1][1] < seq[i][1]]


def distribution_report(md_text: str, max_per_anchor: int = DEFAULT_MAX_PER_ANCHOR) -> dict:
    runs = anchor_runs(md_text)
    total = sum(len(r) for _a, r in runs)
    over = overstacked(md_text, max_per_anchor)
    worst = max((len(r) for _a, r in runs), default=0)
    return {
        "total_imgs": total,
        "distinct_anchors": len(runs),
        "worst_run": worst,
        "max_per_anchor": max_per_anchor,
        "overstacked": [{"anchor": a[:40], "count": len(refs),
                         "files": [f.split("]-")[-1] for f in refs]} for a, refs in over],
        "ok": not over,
    }


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description="圖片分佈塌陷檢核(§ S4.5.11)")
    ap.add_argument("md")
    ap.add_argument("--max-per-anchor", type=int, default=DEFAULT_MAX_PER_ANCHOR)
    a = ap.parse_args()
    rep = distribution_report(Path(a.md).read_text(encoding="utf-8"), a.max_per_anchor)
    print(f"[dist] {rep['total_imgs']} 圖 / {rep['distinct_anchors']} anchor / 最擠 {rep['worst_run']} 張 "
          f"/ 門檻 {rep['max_per_anchor']}")
    for o in rep["overstacked"]:
        print(f"  ✗ 塌陷:anchor「{o['anchor']}…」掛 {o['count']} 張 {o['files']}")
    sys.exit(0 if rep["ok"] else 1)
