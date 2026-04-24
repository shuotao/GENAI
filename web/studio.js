// ─────────────────────────────────────────────────────────
//  好學生筆記工作室 - Studio Logic v3
// ─────────────────────────────────────────────────────────

// ── State ──
let srtContent = '';
let rawCleaned = '';   // Phase A output (client-side QAQC only)
let cleanedMd  = '';   // Phase B output (after Gemini polish)
let enhancedMd = '';   // Step 3 output
let notesMd    = '';   // Step 4 output

// ── Constants ──
const CHUNK_DURATION = 600;
const GROQ_URL = 'https://api.groq.com/openai/v1/audio/transcriptions';

// Typo & hallucination lists are loaded from /dict/*.json at startup
// (see loadDictionaries() below). Hardcoded fallbacks here keep the app
// functional if the dict/ fetch fails (file:// access restrictions, etc.).
let TYPO_FIXES = {
    '剪報': '簡報', '因該': '應該', '在來': '再來',
};

let HALLUCINATION_PREFIXES = [
    '內容包含：', '這是一段關於技術開發', '這是一段繁體中文',
    '请注意', 'Please note', 'Thank you', 'thanks for',
    'Subtitles', 'Subscribe', 'sub', '字幕由',
];

let ACTIVE_DOMAIN = null;          // Currently selected domain overlay
let DICT_LOADED = false;           // Set true once initial fetch completes

// Core rules loaded from prompts/qaqc_core_rules.md — SSoT for Phase B / Step 3 / Step 4.
// If fetch fails (file://, offline), we fall back to inline minimum rules below.
let CORE_RULES_TEXT = '';
const CORE_RULES_PATHS = ['../prompts/qaqc_core_rules.md', '/prompts/qaqc_core_rules.md'];

async function loadCoreRules() {
    for (const path of CORE_RULES_PATHS) {
        try {
            const res = await fetch(path, { cache: 'no-cache' });
            if (res.ok) {
                CORE_RULES_TEXT = await res.text();
                console.log(`[rules] loaded from ${path} (${CORE_RULES_TEXT.length} chars)`);
                return;
            }
        } catch { /* try next */ }
    }
    console.warn('[rules] could not fetch prompts/qaqc_core_rules.md — using inline fallbacks');
}

function rulesSection(startMarker, endMarker) {
    // Extract a section of CORE_RULES_TEXT between two H2 markers.
    if (!CORE_RULES_TEXT) return '';
    const start = CORE_RULES_TEXT.indexOf(startMarker);
    if (start < 0) return '';
    const endRel = endMarker ? CORE_RULES_TEXT.indexOf(endMarker, start) : -1;
    const end = endRel > 0 ? endRel : CORE_RULES_TEXT.length;
    return CORE_RULES_TEXT.slice(start, end).trim();
}

async function loadDictionaries(domain) {
    ACTIVE_DOMAIN = domain || null;
    try {
        const mod = await import('./dict-loader.js');
        const [typo, prefixes] = await Promise.all([
            mod.loadTypoDict(ACTIVE_DOMAIN),
            mod.loadHallucinationPrefixes(),
        ]);
        TYPO_FIXES = typo;
        HALLUCINATION_PREFIXES = prefixes;
        DICT_LOADED = true;
        console.log(`[dict] loaded: base${ACTIVE_DOMAIN ? ` + ${ACTIVE_DOMAIN}` : ''} `
                    + `(${Object.keys(TYPO_FIXES).length} typos, `
                    + `${HALLUCINATION_PREFIXES.length} prefixes)`);
    } catch (err) {
        console.warn('[dict] failed to load dict/, using hardcoded fallbacks:', err.message);
    }
}

// ─────────────────────────────────────────────────────────
//  Utility
// ─────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function downloadFile(filename, text) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
}

// Build a session-shaped ZIP mirroring the CLI `sessions/<slug>/` layout,
// so the user can unzip it directly into their local sessions/ dir.
// Requires JSZip (loaded in studio.html via CDN).
//
// Callable after ANY step — user can export at Step 1, 2, 3, or 4 end; the
// metadata.json reflects exactly how far the pipeline has been run (stop_at).
async function downloadSessionZip(sessionSlug) {
    if (typeof JSZip === 'undefined') {
        alert('JSZip 未載入;無法匯出 ZIP。請確認 studio.html 的 CDN 可存取。');
        return;
    }
    const zip = new JSZip();
    const folder = zip.folder(sessionSlug);

    // Core artifacts (only include files that exist in current state)
    if (srtContent) folder.file('transcript.srt', srtContent);
    if (cleanedMd) folder.file('cleaned.md', cleanedMd);
    if (enhancedMd) folder.file('enhanced.md', enhancedMd);
    if (notesMd) {
        const identity = ($('identity-input') && $('identity-input').value.trim()) || 'notes';
        folder.file(`notes_${identity}.md`, notesMd);
    }

    // Context (from Step 1 textarea, raw form)
    const ctx = ($('context-input') ? $('context-input').value : '').trim();
    if (ctx) folder.file('context.txt', ctx);

    // Determine stop_at based on what artifacts were produced — aligns with CLI
    // session.py --stop-at semantics so Web-exported sessions re-import cleanly.
    let stopAt = 'transcribe';
    if (cleanedMd) stopAt = 'phase-b';
    if (enhancedMd) stopAt = 'enhance';
    if (notesMd) stopAt = 'notes';

    // Metadata — schema aligned with scripts/session.py metadata writer.
    const today = new Date().toISOString().slice(0, 10);
    const identity = ($('identity-input') && $('identity-input').value.trim()) || null;

    const countChars = (s) => ({
        no_space: (s || '').replace(/\s+/g, '').length,
        chinese: ((s || '').match(/[一-鿿]/g) || []).length,
    });
    const rawM = countChars(rawCleaned);
    const cleanedM = countChars(cleanedMd);
    const enhancedM = countChars(enhancedMd);
    const notesM = countChars(notesMd);

    const meta = {
        session_id: sessionSlug,
        created_at: today,
        source: 'web-studio',
        domain_candidate: ACTIVE_DOMAIN,
        identity,
        stop_at: stopAt,
        transcription: {
            engine: 'Groq Whisper large-v3',
            context_bytes: new TextEncoder().encode(ctx).length,
            original_chars_no_space: rawM.no_space,
            original_chinese_chars: rawM.chinese,
        },
        qaqc: {
            phase_a_chars_no_space: rawM.no_space,
            phase_a_chinese_chars: rawM.chinese,
            phase_b: cleanedMd ? {
                in_chars_no_space: rawM.no_space,
                out_chars_no_space: cleanedM.no_space,
                ratio_no_space: rawM.no_space
                    ? +(cleanedM.no_space / rawM.no_space).toFixed(4) : null,
                ratio_chinese: rawM.chinese
                    ? +(cleanedM.chinese / rawM.chinese).toFixed(4) : null,
            } : null,
            enhance: enhancedMd ? {
                in_chars_no_space: cleanedM.no_space,
                out_chars_no_space: enhancedM.no_space,
                ratio_no_space: cleanedM.no_space
                    ? +(enhancedM.no_space / cleanedM.no_space).toFixed(4) : null,
            } : null,
            notes: notesMd ? {
                source: enhancedMd ? 'enhanced.md' : 'cleaned.md',
                in_chars_no_space: (enhancedMd ? enhancedM : cleanedM).no_space,
                out_chars_no_space: notesM.no_space,
                ratio_no_space: (enhancedMd ? enhancedM : cleanedM).no_space
                    ? +(notesM.no_space / (enhancedMd ? enhancedM : cleanedM).no_space).toFixed(4)
                    : null,
            } : null,
            structured_srt_produced: false,
        },
        artifacts: {
            source: null,   // Web can't symlink; audio stays on user's device
            context: ctx ? 'context.txt' : null,
            transcript_srt: srtContent ? 'transcript.srt' : null,
            cleaned_srt: null,   // Web does not produce Phase A cleaned.srt separately
            cleaned_md: cleanedMd ? 'cleaned.md' : null,
            enhanced_md: enhancedMd ? 'enhanced.md' : null,
            notes_md: notesMd ? `notes_${identity || 'notes'}.md` : null,
            transcript_cleaned_srt: null,
        },
    };
    folder.file('metadata.json', JSON.stringify(meta, null, 2));

    const blob = await zip.generateAsync({ type: 'blob' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${sessionSlug}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
}

function makeSessionSlug() {
    const today = new Date().toISOString().slice(0, 10);
    const fileName = $('file-input') && $('file-input').files[0]
        ? $('file-input').files[0].name.replace(/\.[^.]+$/, '')
        : 'web-session';
    const slug = fileName.replace(/[^\w.\-]/g, '').replace(/-+/g, '-');
    return `${today}_${slug || 'web-session'}`;
}

function formatSrtTime(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 1000);
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
}

function showProgress(stepN) {
    const el = $(`prog-${stepN}`);
    el.classList.add('show');
    el.querySelector(`#prog-${stepN}-lines`).innerHTML = '';
    el.querySelector(`#prog-${stepN}-bar`).style.width = '0%';
}

function addProgressLine(stepN, text, status) {
    const line = document.createElement('div');
    line.className = `prog-line ${status}`;
    line.textContent = text;
    $(`prog-${stepN}-lines`).appendChild(line);
}

function setProgressBar(stepN, pct) {
    $(`prog-${stepN}-bar`).style.width = pct + '%';
}

function showResult(stepN) {
    $(`res-${stepN}`).classList.add('show');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─────────────────────────────────────────────────────────
//  Step Navigation
// ─────────────────────────────────────────────────────────

// Sync any pending edits in Step 2 edit textarea back to cleanedMd
function syncStep2Edits() {
    const editEl = $('res-2-edit');
    if (editEl && editEl.value && editEl.value !== cleanedMd) {
        cleanedMd = editEl.value;
        $('res-2-text').innerHTML = marked.parse(cleanedMd);
        $('res-2-stat').textContent = `${cleanedMd.length} 字 (已手動修改)`;
    }
}

function goToStep(n) {
    // Before leaving Step 2, sync any edits
    syncStep2Edits();
    document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
    $(`step-${n}`).classList.add('active');
    for (let i = 1; i <= 4; i++) {
        const dot = $(`dot-${i}`);
        const lbl = $(`lbl-${i}`);
        dot.classList.remove('active', 'done');
        lbl.classList.remove('active');
        if (i < n) dot.classList.add('done');
        if (i === n) { dot.classList.add('active'); lbl.classList.add('active'); }
    }
    // Populate Step 3 preview with Step 2 result whenever entering Step 3
    if (n === 3 && cleanedMd) {
        $('step3-preview').innerHTML = marked.parse(cleanedMd);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ─────────────────────────────────────────────────────────
//  Garbled Text Detection
// ─────────────────────────────────────────────────────────

function isGarbled(text) {
    // Rules: see prompts/qaqc_core_rules.md § R1.2.
    // Previously `length < 2 → true`, which silently dropped valid single-char
    // Chinese replies like "對", "嗯". Relaxed to empty-only.
    if (!text) return true;
    const cjkRe = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef，。！？、；：「」『』（）《》〈〉—…·～]/g;
    const cjkCount = (text.match(cjkRe) || []).length;
    const totalNonSpace = text.replace(/\s/g, '').length;
    if (totalNonSpace === 0) return true;
    const cjkRatio = cjkCount / totalNonSpace;
    if (cjkRatio < 0.25 && totalNonSpace > 10) return true;
    if (/[\ufffd]/.test(text)) return true;
    const noiseRe = /[┌┐└┘├┤┬┴┼│─⊇◡◬Ⓓ჏ს⓪①②③④⑤⑥⑦⑧⑨]/g;
    if ((text.match(noiseRe) || []).length > 1) return true;
    const exoticRe = /[\u10a0-\u10ff\u0600-\u06ff\u0400-\u04ff\u0e00-\u0e7f\u0900-\u097f]/g;
    if ((text.match(exoticRe) || []).length > 0) return true;
    const longLatinRun = /(?:[a-zA-Z]{2,}\s+){5,}/;
    if (longLatinRun.test(text) && cjkRatio < 0.5) return true;
    return false;
}

// ─────────────────────────────────────────────────────────
//  Audio → WAV Chunks
// ─────────────────────────────────────────────────────────

function writeString(view, offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
}

function audioBufferToWav(buf) {
    const ch = buf.getChannelData(0);
    const sr = buf.sampleRate;
    const len = ch.length * 2 + 44;
    const ab = new ArrayBuffer(len);
    const v = new DataView(ab);
    writeString(v, 0, 'RIFF');
    v.setUint32(4, len - 8, true);
    writeString(v, 8, 'WAVE');
    writeString(v, 12, 'fmt ');
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);
    v.setUint16(22, 1, true);
    v.setUint32(24, sr, true);
    v.setUint32(28, sr * 2, true);
    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    writeString(v, 36, 'data');
    v.setUint32(40, ch.length * 2, true);
    let off = 44;
    for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]));
        v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        off += 2;
    }
    return new Blob([ab], { type: 'audio/wav' });
}

async function fileToChunks(file) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const arrayBuf = await file.arrayBuffer();
    const audioBuf = await ctx.decodeAudioData(arrayBuf);
    const duration = audioBuf.duration;
    const targetSR = 16000;
    const numChunks = Math.ceil(duration / CHUNK_DURATION);
    const chunks = [];
    for (let i = 0; i < numChunks; i++) {
        const start = i * CHUNK_DURATION;
        const end = Math.min(start + CHUNK_DURATION, duration);
        const chunkDur = end - start;
        const offCtx = new OfflineAudioContext(1, Math.ceil(chunkDur * targetSR), targetSR);
        const src = offCtx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(offCtx.destination);
        src.start(0, start, chunkDur);
        const rendered = await offCtx.startRendering();
        chunks.push(audioBufferToWav(rendered));
    }
    await ctx.close();
    return { chunks, duration };
}

// ─────────────────────────────────────────────────────────
//  Groq Whisper API
// ─────────────────────────────────────────────────────────

async function callGroqWhisper(audioBlob, apiKey, contextPrompt) {
    const basePrompt = '這是一段繁體中文錄音。';
    const maxPromptLen = 896;
    let finalPrompt = basePrompt;
    if (contextPrompt) {
        const prefix = `${basePrompt} 內容包含：`;
        const suffix = '。';
        const budget = maxPromptLen - prefix.length - suffix.length;
        const trimmed = budget > 0 ? contextPrompt.slice(0, budget) : '';
        finalPrompt = `${prefix}${trimmed}${suffix}`;
    }
    const fd = new FormData();
    fd.append('file', audioBlob, 'audio.wav');
    fd.append('model', 'whisper-large-v3');
    fd.append('response_format', 'verbose_json');
    fd.append('language', 'zh');
    fd.append('temperature', '0.0');
    fd.append('prompt', finalPrompt);
    const resp = await fetch(GROQ_URL, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${apiKey}` },
        body: fd,
    });
    if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(`Groq API ${resp.status}: ${errText}`);
    }
    return resp.json();
}

// ─────────────────────────────────────────────────────────
//  Gemini API (with retry + model fallback)
// ─────────────────────────────────────────────────────────

function getGeminiKey() {
    // Step 2 and Step 3 share the same key; prefer step-2 field if filled
    return ($('gemini-key-2').value || '').trim();
}

async function callGemini(prompt, apiKey, model) {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.2, maxOutputTokens: 65536 },
        }),
    });
    if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(`Gemini ${resp.status} [${model}]: ${errText.substring(0, 200)}`);
    }
    const data = await resp.json();
    return data.candidates[0].content.parts[0].text;
}

async function callGeminiWithRetry(prompt, apiKey, stepN, preferredModel) {
    const models = [
        preferredModel || 'gemini-2.5-flash',
        'gemini-2.5-flash',
        'gemini-2.5-pro',
    ].filter((v, i, a) => a.indexOf(v) === i);

    for (const model of models) {
        for (let attempt = 1; attempt <= 2; attempt++) {
            try {
                addProgressLine(stepN, `⏳ ${model} (第${attempt}次)...`, 'run');
                return await callGemini(prompt, apiKey, model);
            } catch (err) {
                const is429 = err.message.includes('429');
                if (is429 && attempt === 1) {
                    addProgressLine(stepN, '⚠ 速率限制，等待 20 秒...', 'fail');
                    await sleep(20000);
                    continue;
                }
                if (is429) {
                    addProgressLine(stepN, `⚠ ${model} 配額已滿，換下一個...`, 'fail');
                    break;
                }
                throw err;
            }
        }
    }
    throw new Error('所有 Gemini 模型都無法使用，請檢查 API Key 或稍後再試');
}

// ─────────────────────────────────────────────────────────
//  Step 1: Transcribe
// ─────────────────────────────────────────────────────────

async function runTranscribe() {
    const file = $('file-input').files[0];
    const apiKey = $('groq-key').value.trim();
    const context = $('context-input').value.replace(/\n/g, ', ').trim();
    if (!file) return alert('請先上傳音訊檔案');
    if (!apiKey) return alert('請輸入 Groq API Key');

    const btn = $('btn-transcribe');
    btn.disabled = true;
    showProgress(1);

    try {
        addProgressLine(1, '⏳ 正在解碼音訊...', 'run');
        const { chunks, duration } = await fileToChunks(file);
        addProgressLine(1, `✓ 時長 ${Math.round(duration)}秒，${chunks.length} 段`, 'ok');
        setProgressBar(1, 10);

        const allSegments = [];
        let globalIdx = 1;
        for (let i = 0; i < chunks.length; i++) {
            addProgressLine(1, `⏳ 轉錄 ${i+1}/${chunks.length} ...`, 'run');
            const timeOffset = i * CHUNK_DURATION;
            const result = await callGroqWhisper(chunks[i], apiKey, context);
            if (result.segments) {
                for (const seg of result.segments) {
                    const text = (seg.text || '').trim();
                    if (!text) continue;
                    allSegments.push({
                        idx: globalIdx++,
                        start: seg.start + timeOffset,
                        end: seg.end + timeOffset,
                        text,
                    });
                }
            }
            addProgressLine(1, `✓ 片段 ${i+1} 完成`, 'ok');
            setProgressBar(1, 10 + 80 * ((i+1) / chunks.length));
        }

        srtContent = allSegments.map(s =>
            `${s.idx}\n${formatSrtTime(s.start)} --> ${formatSrtTime(s.end)}\n${s.text}\n`
        ).join('\n');

        setProgressBar(1, 100);
        addProgressLine(1, `✓ 共 ${allSegments.length} 句`, 'ok');
        $('res-1-text').value = srtContent;
        $('res-1-stat').textContent = `${allSegments.length} segments · ${Math.round(duration)}s`;
        showResult(1);
    } catch (err) {
        addProgressLine(1, `✗ ${err.message}`, 'fail');
    } finally {
        btn.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────
//  Step 2: QAQC (Phase A) + Gemini Polish (Phase B)
// ─────────────────────────────────────────────────────────

function runPhaseA(stepN) {
    // Client-side QAQC: returns raw cleaned text array
    addProgressLine(stepN, '── Phase A：自動清理 ──', 'run');
    const input = srtContent || '';
    const rawBlocks = input.trim().split(/\n\n+/);
    const texts = [];

    for (const block of rawBlocks) {
        const lines = block.split('\n');
        if (lines.length >= 3 && /-->/.test(lines[1])) {
            texts.push(lines.slice(2).join(' '));
        } else if (lines.length >= 2 && /-->/.test(lines[0])) {
            texts.push(lines.slice(1).join(' '));
        } else {
            const joined = lines.join(' ').trim();
            if (joined && !/^\d+$/.test(joined)) texts.push(joined);
        }
    }
    addProgressLine(stepN, `✓ 解析 ${texts.length} 個區塊`, 'ok');

    // Filter hallucinations
    let removedH = 0, removedG = 0;
    let phase1 = [];
    for (const t of texts) {
        const trimmed = t.trim();
        if (!trimmed) { removedH++; continue; }
        if (HALLUCINATION_PREFIXES.some(p => trimmed.startsWith(p) || trimmed.toLowerCase().startsWith(p.toLowerCase()))) {
            removedH++; continue;
        }
        phase1.push(trimmed);
    }
    addProgressLine(stepN, `✓ 移除 ${removedH} 個幻覺段落`, 'ok');

    // Filter garbled
    let phase2 = [];
    for (const t of phase1) {
        if (isGarbled(t)) { removedG++; continue; }
        phase2.push(t);
    }
    addProgressLine(stepN, `✓ 過濾 ${removedG} 個亂碼段落`, 'ok');

    // Fix typos
    let phase3 = phase2.map(t => {
        let c = t.replace(/ {2,}/g, ' ').trim();
        for (const [wrong, right] of Object.entries(TYPO_FIXES)) c = c.replaceAll(wrong, right);
        return c;
    }).filter(t => t.length > 0);

    // Simple merge (for raw output)
    rawCleaned = phase3.join('\n');
    addProgressLine(stepN, `✓ Phase A 完成，剩餘 ${phase3.length} 句 (${rawCleaned.length} 字)`, 'ok');

    return rawCleaned;
}

async function runPhaseB(rawText, apiKey, stepN) {
    // Gemini polish: add punctuation, connective words, paragraphs.
    // Core rules come from prompts/qaqc_core_rules.md § R2 (SSoT).
    // Web-specific: the user may paste 當下 context in Step 1 textarea; we
    // pass it through here as a domain hint (preserving Web's interactive edge).
    addProgressLine(stepN, '── Phase B：AI 校稿 ──', 'run');

    const r2Rules = rulesSection('## R2. Phase B 校稿核心鐵律', '## R3.') || `
### 必須做的事:
1. 補上標點符號、接續詞、合併破碎斷行、依語意分段、插入 Markdown 標題
### 嚴禁:
- 嚴禁刪減、濃縮、摘要、改語氣、第三人稱描述、省略細節
### 字數檢查:
- 輸出字數必須落在輸入 95%-105% 之間`;

    const ctxInput = ($('context-input') ? $('context-input').value : '').trim();
    const ctxBlock = ctxInput
        ? `\n## 領域背景(使用者當下提供,供專名校正參考)\n${ctxInput}\n`
        : '';

    const prompt = `你是一位逐字稿校稿專家。請對以下語音轉錄的原始文字進行校稿。

${r2Rules}
${ctxBlock}
## 原始逐字稿(${rawText.length} 字)
${rawText}`;

    const model = $('gemini-model') ? $('gemini-model').value : 'gemini-2.5-flash';
    cleanedMd = await callGeminiWithRetry(prompt, apiKey, stepN, model);

    // Verify output length
    const ratio = cleanedMd.length / rawText.length;
    if (ratio < 0.9) {
        addProgressLine(stepN, `⚠ 警告：輸出 ${cleanedMd.length} 字，僅為原文 ${Math.round(ratio*100)}%，可能有省略`, 'fail');
    }

    addProgressLine(stepN, `✓ Phase B 完成 (${cleanedMd.length} 字)`, 'ok');
    return cleanedMd;
}

async function runStep2(withGemini) {
    const btn = $('btn-qaqc');
    const btn2 = $('btn-qaqc-only');
    btn.disabled = true;
    btn2.disabled = true;
    showProgress(2);
    setProgressBar(2, 5);

    try {
        // Phase A: client-side QAQC
        const rawText = runPhaseA(2);
        setProgressBar(2, 40);

        if (withGemini) {
            const apiKey = getGeminiKey();
            if (!apiKey) {
                addProgressLine(2, '⚠ 未填 Gemini API Key，跳過 Phase B', 'fail');
                cleanedMd = rawText;
            } else {
                await runPhaseB(rawText, apiKey, 2);
            }
        } else {
            // No Gemini, just use raw cleaned text with basic paragraph merge
            const lines = rawText.split('\n').filter(l => l.trim());
            const paragraphs = [];
            let current = '';
            for (const line of lines) {
                current += line;
                if (/[。！？]$/.test(line) || current.length > 400) {
                    paragraphs.push(current);
                    current = '';
                }
            }
            if (current) paragraphs.push(current);
            cleanedMd = paragraphs.join('\n\n');
        }

        setProgressBar(2, 100);
        $('res-2-text').innerHTML = marked.parse(cleanedMd);
        $('res-2-stat').textContent = `${cleanedMd.length} 字`;
        showResult(2);

    } catch (err) {
        addProgressLine(2, `✗ ${err.message}`, 'fail');
        // Fallback: use raw cleaned text
        if (rawCleaned) {
            cleanedMd = rawCleaned;
            addProgressLine(2, '💡 已使用未校稿版本作為備用', 'fail');
            $('res-2-text').innerHTML = marked.parse(cleanedMd);
            $('res-2-stat').textContent = `${cleanedMd.length} 字 (未校稿)`;
            showResult(2);
        }
    } finally {
        btn.disabled = false;
        btn2.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────
//  Step 3: Knowledge Enhancement (keyword-driven)
// ─────────────────────────────────────────────────────────

async function runEnhance() {
    const apiKey = getGeminiKey();
    if (!apiKey) return alert('請輸入 Gemini API Key（在 Step 2 已填則自動帶入）');

    const keywordsRaw = $('keywords-input').value.trim();
    const keywords = keywordsRaw
        ? keywordsRaw.split(/[,，\n]+/).map(k => k.trim()).filter(Boolean)
        : [];

    const btn = $('btn-enhance');
    btn.disabled = true;
    showProgress(3);
    setProgressBar(3, 10);

    const keywordInstruction = keywords.length > 0
        ? `請**只針對以下指定的關鍵字**進行補充（不要自行增加其他術語）：\n${keywords.map(k => `- ${k}`).join('\n')}`
        : `請自動找出文中的專業術語和關鍵概念進行補充。`;

    const r4Rules = rulesSection('## R4. 專有名詞補充', '## R5.') || `
1. 完整保留原文,不得修改、刪除、改寫、摘要
2. 補充插入在首次提及該術語的段落之後,嚴禁統一放在文末
3. 每個術語只在首次出現時補充一次
4. 補充區塊上下各保留一個空行
5. 格式:\`> **專業知識補充:[術語名稱]**\` 區塊`;

    const prompt = `你是一位專業知識補充專家。請閱讀以下逐字稿,在文中適當位置插入專業知識補充區塊。

## 補充目標
${keywordInstruction}

${r4Rules}

## 原始逐字稿
${cleanedMd}`;

    try {
        addProgressLine(3, keywords.length > 0
            ? `⏳ 針對 ${keywords.length} 個關鍵字進行補充...`
            : '⏳ 自動識別術語並補充...', 'run');
        setProgressBar(3, 20);

        const model = $('gemini-model').value;
        enhancedMd = await callGeminiWithRetry(prompt, apiKey, 3, model);
        setProgressBar(3, 100);
        addProgressLine(3, '✓ 知識補充完成', 'ok');

        $('res-3-text').innerHTML = marked.parse(enhancedMd);
        $('res-3-stat').textContent = `${enhancedMd.length} 字`;
        showResult(3);
    } catch (err) {
        addProgressLine(3, `✗ ${err.message}`, 'fail');
        addProgressLine(3, '💡 可點「跳過此步驟」繼續', 'fail');
    } finally {
        btn.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────
//  Step 4: Good Student Notes
// ─────────────────────────────────────────────────────────

async function runNotes() {
    const identity = $('identity-input').value.trim();
    const apiKey = getGeminiKey();
    if (!identity) return alert('請輸入你的專業身份');
    if (!apiKey) return alert('請先在 Step 2 輸入 Gemini API Key');

    const sourceContent = enhancedMd || cleanedMd;
    if (!sourceContent) return alert('沒有可用的逐字稿內容');

    const btn = $('btn-notes');
    btn.disabled = true;
    showProgress(4);
    addProgressLine(4, `⏳ 以「${identity}」視角生成好學生筆記...`, 'run');
    setProgressBar(4, 10);

    const r3Rules = rulesSection('## R3. 好學生筆記生成規則', '## R4.') || `
1. 完整保留原文(字數 95%-105%)
2. 在每個段落或重要概念之後,加入立場類比區塊
3. 開頭加入 📝 學習摘要、結尾加入 💡 核心洞察
4. 類比必須合理且有意義;區塊上下各空一行`;

    const prompt = `你是一個「好學生筆記」生成系統。請根據以下逐字稿內容,以「${identity}」的立場,生成立場置入的學習筆記。

## 你的立場
${identity}

${r3Rules}

## 必須出現的結構(依順序)

1. 開頭:\`> 📝 **學習摘要**\` 框,含「核心主題」與「${identity}視角的關鍵收穫 2-3 點」
2. 原文內容(逐段出現),在合適位置插入 \`> 🎯 **${identity}視角**\` 類比區塊(含類比/應用/連結)
3. 結尾:\`> 💡 **核心洞察**\` 框,用${identity}的語言總結

## 逐字稿內容
${sourceContent}`;

    try {
        setProgressBar(4, 20);
        const model = $('gemini-model').value;
        const notes = await callGeminiWithRetry(prompt, apiKey, 4, model);
        setProgressBar(4, 100);
        addProgressLine(4, '✓ 好學生筆記完成！', 'ok');
        notesMd = notes;
        $('res-4-text').innerHTML = marked.parse(notes);
        $('res-4-stat').textContent = `${notes.length} 字`;
        showResult(4);
    } catch (err) {
        addProgressLine(4, `✗ ${err.message}`, 'fail');
    } finally {
        btn.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────
//  Event Listeners
// ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

    // ── Load shared dictionaries from /dict/ + core rules from /prompts/
    //    Both are fire-and-forget; hardcoded fallbacks keep the app functional
    //    if fetches fail (file:// protocol, offline, etc). ──
    const domainSelect = $('domain-select');
    const initialDomain = domainSelect ? domainSelect.value || null : null;
    loadDictionaries(initialDomain);
    loadCoreRules();  // prompts/qaqc_core_rules.md → CORE_RULES_TEXT
    if (domainSelect) {
        domainSelect.addEventListener('change', () => loadDictionaries(domainSelect.value || null));
    }

    // ── Tabs ──
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const parent = tab.closest('.step');
            parent.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            parent.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            $(tab.dataset.tab).classList.add('active');
        });
    });

    // ── File Upload ──
    const zone = $('upload-zone');
    const fileInput = $('file-input');
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.style.borderColor = '#888'; });
    zone.addEventListener('dragleave', () => { zone.style.borderColor = ''; });
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.style.borderColor = '';
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            onFileSelected();
        }
    });
    fileInput.addEventListener('change', onFileSelected);
    function onFileSelected() {
        const f = fileInput.files[0];
        if (f) {
            zone.classList.add('has-file');
            $('upload-name').textContent = `${f.name} (${(f.size / 1024 / 1024).toFixed(1)} MB)`;
        }
    }

    // ── Step 1 ──
    $('btn-transcribe').addEventListener('click', runTranscribe);
    $('btn-paste-next').addEventListener('click', () => {
        const text = $('paste-input').value.trim();
        if (!text) return alert('請貼上逐字稿內容');
        srtContent = text;
        goToStep(2);
    });
    $('btn-dl-srt').addEventListener('click', () => downloadFile('transcribe.srt', srtContent));
    // Per-step ZIP export — reflects R6.2 "every step is a valid stopping point"
    async function exportZipAtStep() {
        syncStep2Edits();
        await downloadSessionZip(makeSessionSlug());
    }
    ['btn-dl-zip-1', 'btn-dl-zip-2', 'btn-dl-zip-3'].forEach(id => {
        const b = $(id);
        if (b) b.addEventListener('click', exportZipAtStep);
    });
    $('btn-to-2').addEventListener('click', () => goToStep(2));

    // ── Step 2 ──
    $('btn-back-1').addEventListener('click', () => goToStep(1));
    $('btn-qaqc').addEventListener('click', () => runStep2(true));       // with Gemini polish
    $('btn-qaqc-only').addEventListener('click', () => runStep2(false)); // QAQC only
    $('btn-dl-md1').addEventListener('click', () => { syncStep2Edits(); downloadFile('transcript.md', cleanedMd); });
    $('btn-to-3').addEventListener('click', () => goToStep(3));

    // Step 2 result tabs: preview / edit
    document.querySelectorAll('#res-2-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('#res-2-tabs .tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.res2;
            document.querySelectorAll('.res2-pane').forEach(p => p.style.display = 'none');
            $(target).style.display = 'block';
            // When switching to edit, populate textarea with current cleanedMd
            if (target === 'res-2-edit-pane') {
                $('res-2-edit').value = cleanedMd;
            }
            // When switching back to preview, sync edits
            if (target === 'res-2-preview-pane') {
                const edited = $('res-2-edit').value;
                if (edited !== cleanedMd) {
                    cleanedMd = edited;
                    $('res-2-text').innerHTML = marked.parse(cleanedMd);
                    $('res-2-stat').textContent = `${cleanedMd.length} 字 (已手動修改)`;
                }
            }
        });
    });

    // ── Step 3 ──
    $('btn-back-2').addEventListener('click', () => goToStep(2));
    $('btn-enhance').addEventListener('click', runEnhance);
    $('btn-dl-md2').addEventListener('click', () => downloadFile('enhanced.md', enhancedMd));
    $('btn-to-4').addEventListener('click', () => goToStep(4));
    $('btn-skip-3').addEventListener('click', () => {
        enhancedMd = cleanedMd;
        goToStep(4);
    });

    // ── Step 4 ──
    $('btn-back-3').addEventListener('click', () => goToStep(3));
    $('btn-notes').addEventListener('click', runNotes);
    $('btn-dl-md3').addEventListener('click', () => {
        downloadFile('good-student-notes.md', notesMd);
    });
    const zipBtn = $('btn-dl-session-zip');
    if (zipBtn) {
        zipBtn.addEventListener('click', async () => {
            syncStep2Edits();
            const slug = makeSessionSlug();
            await downloadSessionZip(slug);
        });
    }

    // ── Clickable step dots ──
    for (let i = 1; i <= 4; i++) {
        $(`dot-${i}`).style.cursor = 'pointer';
        $(`dot-${i}`).addEventListener('click', () => goToStep(i));
    }

    // ── Sync Gemini key between Step 2 and Step 3 ──
    $('gemini-key-2').addEventListener('input', () => {
        // No separate field in Step 3 anymore; all reads from gemini-key-2
    });

    // ── Help Drawer ──
    const helpData = {
        groq: {
            title: 'Groq API Key',
            html: `
                <p>Groq 提供免費的 Whisper 語音轉錄 API。</p>
                <ol>
                    <li>前往 <a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com/keys</a></li>
                    <li>使用 Google 或 GitHub 帳號登入（免費）</li>
                    <li>點選 <strong>Create API Key</strong></li>
                    <li>複製產生的 Key（格式為 <code>gsk_...</code>）</li>
                    <li>貼回上方輸入欄位即可</li>
                </ol>
                <p>免費方案每日有速率限制，一般個人使用完全足夠。</p>
            `
        },
        gemini: {
            title: 'Gemini API Key',
            html: `
                <p>Gemini API 用於 AI 校稿、知識補充與筆記生成。</p>
                <ol>
                    <li>前往 <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a></li>
                    <li>使用 Google 帳號登入</li>
                    <li>點選 <strong>Create API Key</strong>（建立 API 金鑰）</li>
                    <li>選擇任一 Google Cloud 專案（或建立新專案）</li>
                    <li>複製產生的 Key（格式為 <code>AIza...</code>）</li>
                    <li>貼回上方輸入欄位即可</li>
                </ol>
                <p>免費方案提供每分鐘 15 次請求，足夠一般使用。</p>
            `
        }
    };

    document.querySelectorAll('.help-dot').forEach(dot => {
        dot.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const key = dot.dataset.help;
            const data = helpData[key];
            if (!data) return;
            $('help-content').innerHTML = `<h3>${data.title}</h3>${data.html}`;
            $('help-overlay').classList.add('show');
        });
    });

    $('help-close').addEventListener('click', () => {
        $('help-overlay').classList.remove('show');
    });
    $('help-overlay').addEventListener('click', (e) => {
        if (e.target === $('help-overlay')) {
            $('help-overlay').classList.remove('show');
        }
    });
});
