# 實戰踩過的坑(docs/gotchas.md)

> 自 `CLAUDE.md` 移出(2026-10-12 重構)。CLAUDE.md 是專案憲法,
> 只留原則與索引;本檔是它指向的參考資料。

---

## Common Gotchas(實戰踩過的坑)

這幾個是本專案實際開發時踩過的坑,寫下來避免重蹈:

1. **Groq Whisper prompt 有 896 字元上限**(characters,**不是 bytes**)
   - 2026-05 實測 400 訊息:`prompt length must be 896 characters or fewer, but provided prompt contains 931 characters` → Groq 數的是**字元數**
   - **歷史更正**:本條原寫「896 bytes / ≤290 中文字」,是 2026-04 第一次踩錯時的誤判。byte 上限只是字元上限的更嚴格子集 → 舊的 byte 裁切**不會 400**,但會把中文 context 砍到只剩 ~290 字,白白浪費 ⅔ 容量、減少送進 Whisper 的領域詞、降低辨識品質
   - 解法:送 Groq 前確認整段 prompt(base + 內容包含 + context + 。)**≤ 896 字元**(中文用 `wc -m`,不是 `wc -c`)。CLI `groq_transcribe.py:truncate_prompt` 與 Web `studio.js:callGroqWhisper` 已統一按字元裁切

2. **macOS APFS 是 case-insensitive filesystem**
   - `Gemini.md` 與 `GEMINI.md` 視為同一 inode
   - 要改檔名大小寫時:`mv Gemini.md _tmp.md && mv _tmp.md GEMINI.md` 兩步走,避免誤操作
   - 2026-04-24 把 Gemini.md 重整為 GEMINI.md 時踩到

3. **`dict-loader.js` 需要 HTTP 協議才能 fetch `/dict/*.json`**
   - `file://` 下瀏覽器安全政策擋 fetch,會 fallback 到 studio.js 硬寫的 3 組通用字典
   - 用 `cd web && python3 -m http.server 8080` 才能看到完整 22 組 parenting 詞典
   - GitHub Pages 部署下路徑會是 `/GENAI/dict/`,`dict-loader.js` 用 `../dict/` 相對路徑正確解析

4. **Gemini LLM 讀 SRT 會動時間軸** — 這是架構原則 2 的起源
   - 產「保留時間軸的校稿 SRT」務必走 `--structured`:Python 拆結構、LLM 只看 text 陣列、Python 重組
   - 不要讓 LLM 直接讀 SRT 產 SRT,必失敗

5. **圖片進視覺 LLM 前,由送圖工具先做 EXIF 轉正**
   - 視覺模型讀原始像素、不套 EXIF orientation;手機側拍照(常見 orientation=3/6)不轉正會導致 layout 描述鏡像錯誤
   - 已內建:`describe_images.py` 以 `ImageOps.exif_transpose` 轉正至 `.img_norm/` 暫存(原檔不動);出版壓圖 `compress_images.py` 同樣轉正
   - 手動轉正一律用 PIL `exif_transpose` + 存檔不寫 EXIF;`sips -r` 會留 orientation tag 造成下游二次旋轉

6. **轉錄語言:預設自動偵測,翻譯是之後的獨立步驟** —— 不要在轉錄階段強制語言/順手翻
   - **症狀**:對英文音檔強制 `language=zh` + 中文 prompt,Whisper 會逐段在「照實聽到的英文」與「被逼輸出中文」之間打架,產出**中英沙拉**:有時純中文(硬翻/誤譯,如紅綠燈 green→「藍色」)、有時純英文、有時**英文後面贈送一段中文自我翻譯**塞進同一個 cue。這是 Whisper 語言錯配下的 *translation/repeat hallucination*,**不是翻譯功能**(Whisper 的真翻譯任務只能翻成英文,翻不出中文)。
   - **鐵律**:Step 1 轉錄**只忠實轉出原文**。預設 `language` 不指定 → Whisper 自動偵測;prompt 中性、不宣稱語言(宣稱會把偵測帶偏)。Web `studio.html` 有「音檔語言」下拉(自動/中文/English),CLI 中文走 `groq_transcribe.py`、英文走 `groq_transcribe_en.py`。
   - **翻譯是另一道工**:EN→zh-TW 走結構保留流程 `scripts/lang/en/srt_zhtw.py`(原則 2),由 agent 親翻、1:1 對齊,**絕不**讓 Groq 在轉錄時順手翻(否則同時破壞「忠實原文/零省略」與「時間軸保護」)。
   - **例外:Web Step 2 的 `cleaned.md` 可選「翻譯成繁體中文」**。因為 `cleaned.md` 本就**刻意丟棄時間軸**(Step 2 產物定位),翻譯合併進 Phase B(Gemini 一次「忠實翻譯+校稿」)**不違反原則 2**(沒有時間軸要保護);零省略改用 **1:1 段落對齊**驗證(E3),不用跨語言失效的字數比。**要保留時間軸的翻譯**仍須走 `srt_zhtw.py` 結構保留路徑,不可用此捷徑。
   - **歷史假設更正**:本專案早期假設「音檔永遠是繁體中文」(`language` 寫死 zh),處理非中文音檔即壞。此假設已移除,改為自動偵測 + 可手動覆寫。

7. **吵雜場地的 context prompt 會被 Whisper 吐回成幻覺 —— 轉完先量化,中招就整場無 prompt 重轉**
   - **症狀**:靜音/掌聲/換場等非語音段,Whisper 照著我們給的 prompt 生成,產出「內容包含 X、Y、Z…」(中文)或「Key terms …」(英文)的整條亂碼 cue。它**不只是加噪,是蓋掉真實話語**。
   - **量化**:轉完立刻 `grep -c '內容包含\|字幕由' <srt>`(英文用 `Key terms`)。>0 就整場重來 —— 2026-08-08 COSCUP 11 場中 6 場中招,最高一場 20.8% 的 cue 是純幻覺。
   - **⚠️ 前綴 grep 會漏抓(2026-08-29 MCP8 補充)**:echo **不一定帶「內容包含」前綴**,常見是把 context 的**尾巴逐字吐回**(實例:context 結尾「…Schedule、Python、API、搜尋、篩選、組合材料」原封出現在 cue 裡)。前綴 grep 回 0 不代表乾淨。**補一道 context 詞命中率掃描**:把 `context.txt` 切成詞、對 `cleaned.md` 逐行數命中,**單行命中 ≥4 個 context 詞**即高度可疑,逐條人工判讀。MCP8 四場前綴 grep 只抓到 1 場,補掃後發現**四場全中招**;無 prompt 重轉後 CJK 回升 +17~38%(被幻覺蓋掉的真實內容回來了)。
   - **解方(已內建)**:`GROQ_NO_PROMPT=1`(完全不送 prompt,連 base 句也不送)+ `GROQ_CHUNK_SECONDS=300`(短切段抑制迴圈),`groq_transcribe.py` 與 `groq_transcribe_en.py` 皆支援。實測 echo 歸零、**CJK 字數反增 10–18%**(被蓋掉的內容回來了)。
   - **重轉要整場重建**:`session.py` 拒絕既有目錄,且 `cleaned.md` 與 marker 的字數區間要一致重生 → 先把舊 SRT 複製出去當 Phase B 專名交叉參考,再 `rm -rf` 該 session 重跑。
   - **代價與補償**:無 prompt 會失去專名先驗(如 Open Data→「Open Beta」),改由 Phase B 依 `context.txt` + 官方議程校正(核心鐵律 F1)。**字數門要記得放行**:ASR base 被幻覺灌水時 95–105% 的分母無效,真門是 `build_book_master` 的 self_assert(≥99.5%)與 `publish_qaqc` 字數漂移(<10%)。
   - **副作用:簡體漂移(2026-08-29 引入)**。拿掉 prompt 等於同時拿掉 Whisper 的「繁體中文」語言先驗,輸出會片段性漂移成簡體(MCP8 場 03:11,272 CJK 中 1,059 字為簡體)。這是**確定性字元對映,不該勞動 LLM 逐字改**(原則 6)→ 重轉後、進 Phase B 前跑 `python3 scripts/s2t_normalize.py sessions/<slug>/cleaned.md sessions/<slug>/cleaned.srt --in-place`(OpenCC `s2tw`,只換字形不換詞彙;`transcript.srt` 不可變,工具會自行拒絕)。

---

