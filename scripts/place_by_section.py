#!/usr/bin/env python3
"""place_by_section.py — 章節綁定的確定性投影片放置(Step 4.5 影像放置,§ S4.5.11)。

動機(Fable advisor 2026-07-20):自由 LLM/純字面 DP 放置有「被關鍵字最密段落吸走 → 系統性放太晚」
的單向偏差(deck18 +8、deck19 +5)。逐字稿的 `##` 小標題本身就是主題分段,把它當**硬邊界**:
  Tier A  每張投影片先綁定到一個小節(caption↔小節 相似度,單調不減)→ 誤差被小節寬度封頂
  Tier B  小節內以 deck 序、first-occurrence、step-cap 落到最貼題的段落
LLM 只在「相鄰小節近似平手」或「單節>2 張需細排」時介入(此檔先不呼叫,純確定性)。

輸入:seg_paras.json(段落 {ci,text})、slides.json(投影片 {deck,caption,signal})
輸出:anchors JSON [{deck, after_ci}]
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

CJK = r'一-鿿'
EN = re.compile(r'[A-Za-z][A-Za-z0-9._\-]+')
STOP = set("的了是我你他這那就在有和與也都要把和個一及".split())


def tokens(text: str) -> set[str]:
    t = text.lower()
    toks = set(m.group(0) for m in EN.finditer(t) if len(m.group(0)) >= 2)
    for run in re.findall(f'[{CJK}]+', text):
        for i in range(len(run) - 1):       # CJK 2-gram
            bg = run[i:i+2]
            if bg[0] not in STOP and bg[1] not in STOP:
                toks.add(bg)
    return toks


def sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)               # caption 命中率(0~1)


def build_sections(paras):
    """回傳 [{idx, head_ci, body: [(ci, toks)], head_toks}];含首個 ## 前的 intro 區。"""
    secs = []
    cur = {"idx": 0, "head_ci": paras[0]["ci"], "body": [], "head_toks": set()}
    for p in paras:
        is_head = p["text"].startswith("## ") or (p["text"].startswith("# ") and not p["text"].startswith("## "))
        if is_head and (cur["body"] or secs):   # 新小節
            secs.append(cur)
            cur = {"idx": len(secs), "head_ci": p["ci"], "body": [], "head_toks": tokens(p["text"])}
        else:
            cur["body"].append((p["ci"], tokens(p["text"])))
            if not cur["head_toks"] and is_head:
                cur["head_toks"] = tokens(p["text"])
    secs.append(cur)
    # 小節主題向量 = 標題 + 內文
    for s in secs:
        s["all_toks"] = set(s["head_toks"])
        for _, tk in s["body"]:
            s["all_toks"] |= tk
        if not s["body"]:            # 空節(只有標題)給標題 ci 當 body
            s["body"] = [(s["head_ci"], s["head_toks"])]
    return secs


def assign_sections(slides, secs):
    """Viterbi 單調 DP:把每張投影片綁到小節。狀態=小節 idx,禁回退,前進每格罰分,
    避免被雜訊 sim 一次跳到很後面的小節(greedy 的致命傷)。emission=caption↔小節相似度。"""
    N, M = len(slides), len(secs)
    st = [tokens(sl["caption"] + " " + " ".join(sl.get("signal", []))) for sl in slides]
    emit = [[sim(st[i], secs[j]["all_toks"]) + 0.6 * sim(st[i], secs[j]["head_toks"])
             for j in range(M)] for i in range(N)]
    ADV = 0.28          # 每前進一個小節的罰分(壓抑跳段)
    NEG = -1e9
    dp = [[NEG] * M for _ in range(N)]
    bk = [[0] * M for _ in range(N)]
    for j in range(M):
        dp[0][j] = emit[0][j] - ADV * j          # 首張:從 S0 前進 j 格
        bk[0][j] = j
    for i in range(1, N):
        for j in range(M):
            best, bj = NEG, j
            for k in range(j + 1):               # 前一張在 k ≤ j(單調不回退)
                v = dp[i-1][k] - ADV * (j - k) + emit[i][j]
                if v > best:
                    best, bj = v, k
            dp[i][j], bk[i][j] = best, bj
    j = max(range(M), key=lambda x: dp[N-1][x])
    path = [0] * N
    for i in range(N-1, -1, -1):
        path[i] = j
        j = bk[i][j]
    return path


def place_within(slides, sec_of, secs):
    """小節內:deck 序、first-occurrence、step-cap 落段。"""
    anchors = []
    by_sec = {}
    for sl, si in zip(slides, sec_of):
        by_sec.setdefault(si, []).append(sl)
    for si, group in by_sec.items():
        body = secs[si]["body"]              # [(ci, toks)]
        prev_j = 0
        for sl in group:                     # 已是 deck 序
            st = tokens(sl["caption"] + " " + " ".join(sl.get("signal", [])))
            # first-occurrence:從 prev_j 起,取第一個達門檻的段;否則取分數最高段;decay 壓後段
            best_j, best_s = prev_j, -1
            for j in range(prev_j, len(body)):
                s = sim(st, body[j][1]) * (0.82 ** (j - prev_j))   # 後段 decay
                if s > best_s:
                    best_s, best_j = s, j
                if best_s >= 0.5:            # 夠像就 first-occurrence 早停
                    best_j = j if s == best_s else best_j
                    break
            best_j = min(best_j, prev_j + 2)  # step-cap:單節內一次前進 ≤2 段
            anchors.append({"deck": sl["deck"], "after_ci": body[best_j][0]})
            prev_j = best_j
    anchors.sort(key=lambda x: x["deck"])
    # 全域單調保底(deck 序 after_ci 不得回退)
    mx = 0
    for a in anchors:
        if a["after_ci"] < mx:
            a["after_ci"] = mx
        mx = a["after_ci"]
    return anchors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--paras", default="seg_paras.json")
    ap.add_argument("--slides", default="slides.json")
    ap.add_argument("--out", default="anchors_section.json")
    a = ap.parse_args()
    d = Path(a.session)
    paras = json.loads((d / a.paras).read_text(encoding="utf-8"))
    slides = sorted(json.loads((d / a.slides).read_text(encoding="utf-8")), key=lambda x: x["deck"])
    secs = build_sections(paras)
    sec_of = assign_sections(slides, secs)
    anchors = place_within(slides, sec_of, secs)
    (d / a.out).write_text(json.dumps(anchors, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[section] {len(anchors)} 張;小節綁定: " +
          " ".join(f"d{sl['deck']}→S{si}" for sl, si in zip(slides, sec_of)))


if __name__ == "__main__":
    main()
