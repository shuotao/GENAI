#!/usr/bin/env python3
"""Step 4.5 build：從 master「GenAI2026_day2的全天.md」派生出版用 publish.md + toc.json。

master 保持可讀（含議程、--- 分隔、#### 子標、> 引言、休息小標），這支腳本做確定性轉換成
md_to_html.py 吃得下的格式（只支援 #、## 、### 、*subtitle*、**bold**、![img]()）：
  - 移除 `## 議程` 整段（到下一個 `## ` 前）
  - 移除單獨成行的 `---`
  - 移除「### —— 休息 ——」「### —— 午餐 ——」這類休息小標（議程已表達）
  - `#### ` 降為 `### `
  - 移除 `**講者：**` / `**講題：**` 兩行（章節頭改由 toc.json 驅動）
  - 引言 `> ...`：丟掉重複的 `> 講者：` / `> Office Hour 對談｜` 表頭；其餘（demo 對話）去掉
    `> ` 標記轉成一般段落（保留內容、零省略）
  - 15 個 `## 第N場` → 章節；其餘（# 標題、*subtitle*、### 子標、**bold**）原樣保留

未來貼照片/校稿都改 master 一份即可，再跑這支 + publish_goodedunote.sh 重出版。
"""
import json, re, pathlib, sys

ROOT = pathlib.Path("/Users/shuotaochiang/Desktop/study")
MASTER = ROOT / "GenAI2026_day2的全天.md"
WD = ROOT / "build" / "genai2026-day2"
WD.mkdir(parents=True, exist_ok=True)

# toc：15 場，順序需與 master 的 15 個 `## 第N場` 一致
TOC = [
 {"time":"企業案例","talk":"企業 AI 轉型地圖","speakers":"Happy · 91APP 產品長"},
 {"time":"AI AGENT","talk":"代理人寫作","speakers":"李慕約 · 生成式 AI 年會 策展人"},
 {"time":"企業案例","talk":"打造人人想當勇者的冒險者公會","speakers":"傑哥 · 只要有人社群顧問 執行長"},
 {"time":"企業案例","talk":"一個 80 人團隊在 AI 浪潮裡的真實管理故事","speakers":"Wisely · 創智動能 執行副總"},
 {"time":"企業案例","talk":"賣實體產品的公司，也能長成 AI Native","speakers":"王大皓 · MIXXIN 一起實驗 執行長"},
 {"time":"企業案例","talk":"Leading to Agent-Native Company","speakers":"林裕欽 Kytu Lin · Dcard CEO"},
 {"time":"AI AGENT","talk":"個人化通用助理的未來","speakers":"紀懷新 · Google DeepMind 傑出科學家／研究副總裁"},
 {"time":"AI AGENT","talk":"我的麻瓜 AI Agent 之路","speakers":"Peggy Lo · 非營利組織工作者"},
 {"time":"AI AGENT","talk":"以 AI 創非線性增長","speakers":"汪志謙 · 真觀顧問 & ABT 創始人"},
 {"time":"AI AGENT","talk":"我的程式碼終於活過來了 — 從演算藝術到數位生命體","speakers":"吳哲宇 · 墨雨互動設計 MonoLab"},
 {"time":"AI AGENT","talk":"AI 電馭寫作","speakers":"加恩 · 網路寫作者"},
 {"time":"對談","talk":"Office Hour 對談：從視覺化筆記到 AI","speakers":"Alan 詹雨安 × 李慕約 · Heptabase × 策展人"},
 {"time":"企業案例","talk":"把整個公司變成 Context","speakers":"陳泰呈 Jackle · 卡柏蒂 CUPETIT 資訊長"},
 {"time":"企業案例","talk":"全公司都會用 AI 了，然後呢？","speakers":"海總理 · USPACE AI 長"},
 {"time":"企業案例","talk":"Read the Vibes：一份反生產力宣言","speakers":"Sunny · 薩泰爾娛樂 共同創辦人"},
]

lines = MASTER.read_text(encoding="utf-8").splitlines()
out = []
skip_agenda = False
for ln in lines:
    s = ln.rstrip()
    if s.startswith("## 議程"):
        skip_agenda = True
        continue
    if skip_agenda:
        if s.startswith("## "):
            skip_agenda = False
        else:
            continue
    if s.strip() == "---":
        continue
    if re.match(r"^### —— .* ——\s*$", s):       # 休息/午餐小標
        continue
    if s.startswith("**講者：**") or s.startswith("**講題：**"):
        continue
    if s.startswith(">"):
        body = s[1:].strip()                      # 去 > 與後續空白（含 bare `>` 空行）
        if not body:
            continue                              # 空白引言續行 → 丟
        if body.startswith("講者:") or body.startswith("講者：") or body.startswith("Office Hour 對談"):
            continue                              # 丟重複表頭
        s = body                                  # demo 對話 → 一般段落
    if s.startswith("#### "):
        s = "###" + s[4:]
    out.append(s)

publish_md = "\n".join(out).strip() + "\n"
(WD / "publish.md").write_text(publish_md, encoding="utf-8")
(WD / "toc.json").write_text(json.dumps(TOC, ensure_ascii=False, indent=2), encoding="utf-8")

n_ch = sum(1 for l in out if l.startswith("## "))
chin = len(re.findall(r"[一-鿿]", publish_md))
print(f"[build] publish.md: {WD/'publish.md'}")
print(f"[build] toc.json:   {WD/'toc.json'} ({len(TOC)} entries)")
print(f"[build] ## 章節數 = {n_ch} (期望 15；與 toc 長度{'相符' if n_ch==len(TOC) else '不符!'})")
print(f"[build] 中文字數 = {chin}")
# 殘留不支援語法檢查
for pat,label in [(r"^#### ","H4"),(r"^> ","blockquote"),(r"^- ","bullet"),(r"^\|","table"),(r"^---$","hr")]:
    c=sum(1 for l in out if re.match(pat,l))
    if c: print(f"[warn] 殘留 {label}: {c}")
if n_ch != len(TOC):
    sys.exit("ERROR: 章節數與 toc 不符")
