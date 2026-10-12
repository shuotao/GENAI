# 工具清單(docs/tools.md)

> **本檔是 `scripts/` 公開工具的唯一清單家**(§ 文件同步守則)。
> 由 `scripts/tests/test_docs_sync.py` 機械守門:每個 `scripts/*.py|sh` 與
> `scripts/lang/**/*.py` 都必須出現在本檔,否則測試失敗。
> 新增工具 = 在這裡補一列,不必同時改 CLAUDE.md 與 README。
> 一行描述取自各檔的 module docstring / 檔頭註解;詳細用法看該檔 `--help`。

| 工具 | 一行用途 |
|---|---|
| `scripts/build_book_master.py` | Step 4.5 書本 master 收斂器(取代寫死的 build_genai2026_day1/day2.py)。 |
| `scripts/build_genai2026_day1.py` | Step 4.5 build：從 master「GenAI2026_day1的七場.md」派生出版用 publish.md + toc.json。 |
| `scripts/build_genai2026_day2.py` | Step 4.5 build：從 master「GenAI2026_day2的全天.md」派生出版用 publish.md + toc.json。 |
| `scripts/classify_session.py` | Step 4.5 場次狀態分類器（確定性,無 LLM — 見 CLAUDE.md 原則 6 / prompts/publish_qaqc.md § S4.5.13）。 |
| `scripts/compare_placement.py` | 比對一組放置(anchors: deck→after_ci)與 ground-truth,算語意相符率。 |
| `scripts/compress_images.py` | 壓縮 + EXIF 自動轉正圖片到目標目錄(不改原檔)。Step 5 出版前用,省 Firebase 流量。 |
| `scripts/dedupe_images.py` | dedupe_images.py — 重複圖片檢測與去重(§ S4.5.12 / § S6.12)。 |
| `scripts/describe_images.py` | describe_images.py — 圖片理解 orchestrator(確定性外殼,LLM 只做看圖判斷)。 |
| `scripts/dialogue_check.py` | scripts/dialogue_check.py — 多講者座談對談歸屬與順序檢核(§ S4.5.14) |
| `scripts/finalize_placement.py` | finalize_placement.py — 依 deck 順序把 anchors 收斂成「單調 + max-2 + 無 -1」的確定性收尾。 |
| `scripts/gnote_db.py` | goodedunote 後台的共用 Firestore 連線層。 |
| `scripts/image_notes_session.py` | scripts/image_notes_session.py — 好學生筆記「圖像版」兩階段工具。 |
| `scripts/img_context_score.py` | img_context_score.py — 圖文相關性計分(確定性,gate 與 Step 6 audit 共用)。 |
| `scripts/import_roster.py` | 把 GWS 的報名資料批次匯入 goodedunote 後台的 Firestore 名冊。 |
| `scripts/inject_ga.py` | 把 GA4 埋點補進「已經產出」的 goodedunote HTML。 |
| `scripts/insert_images.py` | insert_images.py — 自動插圖工具(plan / apply / verify 三模式,確定性)。 |
| `scripts/lock_sessions.py` | 為某本 goodedunote 書的 session 頁加上「前端密碼軟鎖」(校稿期間用)。 |
| `scripts/md_to_a4_png.py` | scripts/md_to_a4_png.py — 把 markdown 確定性渲染成 A4 白底 PNG(多頁),可選疊「好學生筆記」註解。 |
| `scripts/merge_subscriber.py` | 把「同一個人的重複 subscriber 文件」合併到主位址，然後刪掉重複的那筆。 |
| `scripts/normalize_punctuation.py` | Phase C 全形化(確定性,非 LLM)— SSoT: prompts/qaqc_core_rules.md § R7.1 |
| `scripts/optimize_demo_video.py` | Optimize an MP4 demo video for click-to-play use on goodedunote. |
| `scripts/para_len_check.py` | para_len_check.py — Phase B 段落長度量測(§ R2.1:目標每段 60~120 CJK 字,寧短勿長)。 |
| `scripts/phase_d_check.py` | phase_d_check.py — Phase D「只插入、不改寫」的機械證明(§ R8.2)。 |
| `scripts/pipeline_logger.py` | pipeline_logger.py — 「log → check → return-and-improvement」自動化迴圈的基座。 |
| `scripts/place_by_section.py` | place_by_section.py — 章節綁定的確定性投影片放置(Step 4.5 影像放置,§ S4.5.11)。 |
| `scripts/placement_check.py` | placement_check.py — 圖片「分佈塌陷」確定性檢核(§ S4.5.11 / § S6.11)。 |
| `scripts/placement_supervisor.py` | placement_supervisor.py — 圖片放置監管 loop 的確定性驅動器(§ S4.5.11)。 |
| `scripts/prepublish_gate.py` | 出版前強制門(原則 9 / CLAUDE.md)— 由 publish_goodedunote.sh 開頭呼叫。 |
| `scripts/propose_anchors.py` | propose_anchors.py — 插圖 anchor 確定性比對器(純 py 文字比對,零 LLM)。 |
| `scripts/publish_qaqc.py` | scripts/publish_qaqc.py — Step 6 出版後 QAQC 自動審查腳本 |
| `scripts/qaqc_phase_b.py` | qaqc_phase_b.py — Gemini-powered Phase B/Step 3/Step 4 runner (CLI-side) |
| `scripts/retire_list_label.py` | 把一個已退役的名單軌跡標籤從 subscribers.lists[] 移除。 |
| `scripts/s2t_normalize.py` | 簡體漂移正規化 —— 簡體字 → 台灣正體(確定性工具,原則 6)。 |
| `scripts/seed_admin.py` | 種下 goodedunote 後台的兩份基礎字典:管理員白名單與封鎖理由。 |
| `scripts/session.py` | scripts/session.py — 統籌一次音訊轉筆記處理的整條 pipeline |
| `scripts/step45_converge.py` | Step 4.5→5 一致性編排(dry-run,不 deploy)。SSoT: prompts/publish_qaqc.md § S4.5.13。 |
| `scripts/sync_ga_stats.py` | 把 GA4 的文章瀏覽數同步進 Firestore,供後台 /admin/ 顯示。 |
| `scripts/pipeline_autopilot.sh` | pipeline_autopilot.sh — 閉環入口(薄殼):音檔(+圖片)→ Step1→2(B/C/D)→圖片理解→插圖 |
| `scripts/publish_goodedunote.sh` | Step 5(出版層)— 把一篇筆記的 cleaned.md(+toc.json)轉成「多頁式」HTML |
| `scripts/lang/dedup_to_srt.py` | dedup_to_srt.py — 把 vtt_to_txt.py 產出的去滾動文字(`[hh:mm:ss] text` 每行一段) |
| `scripts/lang/en/groq_transcribe_en.py` | Groq Whisper transcription for English audio. |
| `scripts/lang/en/md_to_html.py` | md_to_html.py — cleaned.md → 分頁式 HTML 逐字稿(致敬波隆納 transcript.html 質感)。 |
| `scripts/lang/en/md_translate_zhtw.py` | md_translate_zhtw.py — 將英文 cleaned.md 整檔翻譯為 zh-TW(Gemini Flash)。 |
| `scripts/lang/en/srt_to_md.py` | srt_to_md.py — Stage 2: 去時間軸、合併、通順的對話稿(cleaned.md)。 |
| `scripts/lang/en/srt_translate_zhtw.py` | srt_translate_zhtw.py — 填 srt_zhtw.py workdir 的 zh_parts/(EN cue → zh-TW)。 |
| `scripts/lang/en/srt_zhtw.py` | srt_zhtw.py — English SRT → Traditional-Chinese (zh-TW) subtitle, structure-preserving. |
| `scripts/lang/en/zh_parts_check.py` | zh_parts_check.py — srt_zhtw.py workdir 譯文的機械品質閘。 |
| `scripts/lang/it/batch_accademia.py` | 批次轉錄佛羅倫斯學院美術館導覽音檔 (0-15)，合併為單一 SRT。 |
| `scripts/lang/it/batch_accademia_en.py` | 批次轉錄佛羅倫斯學院美術館導覽音檔 (0-15)，英文模式，合併為單一 SRT。 |
| `scripts/lang/it/batch_qaqc.py` | Batch QAQC Phase A: auto-clean all SRT files to raw text. |
| `scripts/lang/it/clean_srt_it.py` | Clean Italian SRT: remove metadata, hallucinated segments, merge text. |
| `scripts/lang/it/groq_transcribe_it.py` | Groq Whisper transcription for Italian audio. |
| `scripts/lang/it/retry_accademia.py` | Retry failed files (3, 7, 11, 15) and patch into the merged SRT. |
| `scripts/lang/ja/gemini_transcribe_ja.py` | Gemini Transcribe Tool (Japanese version) |
| `scripts/lang/ja/groq_transcribe_ja.py` | Groq Whisper 逐字稿工具 (日文版) |
| `scripts/lang/ja/qaqc_phase_b_ja.py` | qaqc_phase_b_ja.py — Gemini-powered Phase B/Step 3/Step 4 runner (Japanese version) |
| `scripts/lang/ja/qaqc_srt_ja.py` | qaqc_srt_ja.py — SRT 的 QAQC 清理 (Japanese version) |
| `scripts/lang/srt_clean_md.py` | srt_clean_md.py — 階段二:單一 SRT → 去時間軸、合併、通順的 cleaned.md(確定性,不用 LLM)。 |
| `scripts/lang/vtt_to_txt.py` | YouTube 自動字幕 VTT → 去重純文字(確定性,原則 6)。 |
