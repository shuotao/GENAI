#!/usr/bin/env python3
"""Step 4.5 build：從 master「GenAI2026_day1的七場.md」派生出版用 publish.md + toc.json。

master 保持可讀(含議程、--- 分隔、#### 子標),這支腳本做確定性轉換成
md_to_html.py 吃得下的格式:
  - 移除 `## 議程` 整段(到下一個 `## ` 前)
  - 移除單獨成行的 `---`
  - `#### ` 降為 `### `(md_to_html 只支援到 ###)
  - 移除 `**講者:**` / `**講題:**` 兩行(改由 toc.json 驅動章節頭,避免重複)
  - 7 個 `## 第N場` → 章節;其餘(# 標題、### 子標、**bold**、![img]())原樣保留

未來貼照片/校稿都改 master 一份即可,再跑這支 + publish_goodedunote.sh 重出版。
"""
import json, re, pathlib, sys

ROOT = pathlib.Path("/Users/shuotaochiang/Desktop/study")
MASTER = ROOT / "GenAI2026_day1的七場.md"
WD = ROOT / "build" / "genai2026-day1"
WD.mkdir(parents=True, exist_ok=True)

# toc：7 場,順序需與 master 的 7 個 `## 第N場` 一致
TOC = [
    {"time": "企業案例", "talk": "從零開始養一隻會查帳的狗",
     "speakers": "小馮 · 薩泰爾娛樂 全端工程師"},
    {"time": "教學", "talk": "從 Vibe Coding 到真正可以上線的產品:你還差了什麼?",
     "speakers": "沅霖 · Zeabur 創辦人"},
    {"time": "教學", "talk": "Vibe Coding:寫程式,還是開盲盒?",
     "speakers": "高見龍 · 五倍學院 負責人"},
    {"time": "教學", "talk": "Harness Engineering at PicCollage",
     "speakers": "Jocelin · PicCollage Engineering Manager"},
    {"time": "企業案例", "talk": "同事 AI 成癮了",
     "speakers": "Leo · 大師課業 AI 研究所所長"},
    {"time": "企業案例", "talk": "再見了廠商,平台自己建",
     "speakers": "TC · 玉山銀行 副主任工程師"},
    {"time": "企業案例", "talk": "把自己從流程裡抽離:讓 AI 自己評估、自己修、自己升級",
     "speakers": "海總理 · 海的有限公司"},
]

lines = MASTER.read_text(encoding="utf-8").splitlines()
out = []
skip_agenda = False
for ln in lines:
    s = ln.rstrip()
    # 進入 / 離開 議程段
    if s.startswith("## 議程"):
        skip_agenda = True
        continue
    if skip_agenda:
        if s.startswith("## "):      # 下一個 ## → 議程結束
            skip_agenda = False
        else:
            continue
    if s.strip() == "---":            # 去除水平分隔線(md_to_html 會字面顯示)
        continue
    if s.startswith("**講者:**") or s.startswith("**講題:**"):
        continue                       # 章節頭改由 toc 驅動
    if s.startswith("#### "):          # 降一級
        s = "###" + s[4:]
    out.append(s)

publish_md = "\n".join(out).strip() + "\n"
(WD / "publish.md").write_text(publish_md, encoding="utf-8")
(WD / "toc.json").write_text(json.dumps(TOC, ensure_ascii=False, indent=2), encoding="utf-8")

# 自查:## 章節數 == toc 長度
n_ch = sum(1 for l in out if l.startswith("## "))
chin = len(re.findall(r"[一-鿿]", publish_md))
print(f"[build] publish.md: {WD/'publish.md'}")
print(f"[build] toc.json:   {WD/'toc.json'} ({len(TOC)} entries)")
print(f"[build] ## 章節數 = {n_ch} (期望 7;與 toc 長度{'相符' if n_ch==len(TOC) else '不符!'})")
print(f"[build] 中文字數 = {chin}")
if n_ch != len(TOC):
    sys.exit("ERROR: 章節數與 toc 不符,請檢查 master 的 ## 第N場 標題")
