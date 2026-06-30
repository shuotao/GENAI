// ─────────────────────────────────────────────────────────
//  好學生筆記工作室 - Studio Logic v3
// ─────────────────────────────────────────────────────────

// ── State ──
let srtContent = '';
let rawCleaned = '';   // Phase A output (client-side QAQC only)
let cleanedMd  = '';   // Phase B output (after Gemini polish)
let enhancedMd = '';   // Step 3 output
let notesMd    = '';   // Step 4 output
let imageNotesPngs = []; // Step 4 圖文版:[{dataUrl, base64, identity, index}]

// ── Gemini Token Tracking State ──
let sessionTokens = {
    'gemini-2.5-flash': { input: 0, output: 0 },
    'gemini-2.5-pro': { input: 0, output: 0 },
    'gemini-2.5-flash-image': { input: 0, output: 0 }
};

const GEMINI_RATES = {
    'gemini-2.5-flash': { input: 0.075 / 1000000, output: 0.30 / 1000000 },
    'gemini-2.5-pro': { input: 1.25 / 1000000, output: 5.00 / 1000000 },
    'gemini-2.5-flash-image': { input: 0.075 / 1000000, output: 0.30 / 1000000 }
};

function recordGeminiTokens(model, inputTokens, outputTokens) {
    if (!sessionTokens[model]) {
        sessionTokens[model] = { input: 0, output: 0 };
    }
    sessionTokens[model].input += (inputTokens || 0);
    sessionTokens[model].output += (outputTokens || 0);
    updateStatusBar();
}

function updateStatusBar() {
    const apiKey = getGeminiKey();
    const statusDot = $('api-status-dot');
    const statusText = $('api-status-text');
    
    if (statusDot && statusText) {
        if (apiKey) {
            statusDot.className = 'status-indicator ready';
            statusText.textContent = 'API 已連線';
        } else {
            statusDot.className = 'status-indicator';
            statusText.textContent = 'API 未就緒';
        }
    }
    
    const activeModel = ($('gemini-model') ? $('gemini-model').value : 'gemini-2.5-flash');
    if ($('active-model-text')) {
        $('active-model-text').textContent = `Model: ${activeModel}`;
    }
    
    // Accumulate session cost & tokens
    let totalCost = 0;
    let totalInput = 0;
    let totalOutput = 0;
    for (const m in sessionTokens) {
        const usage = sessionTokens[m];
        const rate = GEMINI_RATES[m] || GEMINI_RATES['gemini-2.5-flash'];
        totalInput += usage.input;
        totalOutput += usage.output;
        totalCost += usage.input * rate.input + usage.output * rate.output;
    }
    const totalTokens = totalInput + totalOutput;
    
    if ($('session-tokens-text')) {
        $('session-tokens-text').innerHTML = `${totalInput.toLocaleString()} in / ${totalOutput.toLocaleString()} out <span style="color: #666;">(Total: ${totalTokens.toLocaleString()}, $${totalCost.toFixed(5)})</span>`;
    }
    
    // Projections
    const rates = GEMINI_RATES[activeModel] || GEMINI_RATES['gemini-2.5-flash'];
    
    function getProjHTML(hours) {
        const baseChars = hours * 60 * 200;
        const baseTokens = Math.round(baseChars * 1.8);
        const projInput = Math.round(4 * baseTokens + 10000);
        const projOutput = Math.round(2.3 * baseTokens + 3000);
        const projTotal = projInput + projOutput;
        const projCost = projInput * rates.input + projOutput * rates.output;
        
        let tokenStr = (projTotal / 1000).toFixed(1) + 'K';
        return `${tokenStr} ($${projCost.toFixed(2)})`;
    }
    
    if ($('proj-5h-text')) {
        $('proj-5h-text').innerHTML = getProjHTML(5);
    }
    if ($('proj-7h-text')) {
        $('proj-7h-text').innerHTML = getProjHTML(7);
    }
}

// ── Constants ──
const GROQ_URL = 'https://api.groq.com/openai/v1/audio/transcriptions';
// Groq 單次請求音檔上限約 25MB。小於此值 → 直送原檔(Groq 原生收 mp3/m4a/mp4/wav…,
// 一次回傳就有正確全域時間戳)。大於此值 → 走瀏覽器端 decode→16kHz WAV→切段 fallback。
// 留 1MB margin 避免邊界誤判。
const GROQ_MAX_DIRECT_BYTES = 24 * 1024 * 1024;
// 切段 fallback:每段轉 16kHz mono 16-bit WAV = 32000 bytes/秒。目標每段 ~8MB,
// 上傳快又穩、進度更細;取代舊的 600 秒=19MB 大段(在瀏覽器上傳慢、易卡)。
const WAV_BYTES_PER_SEC = 16000 * 2;
const GROQ_CHUNK_TARGET_BYTES = 4 * 1024 * 1024;
const CHUNK_DURATION = Math.floor(GROQ_CHUNK_TARGET_BYTES / WAV_BYTES_PER_SEC); // ≈ 131 秒 ≈ 4MB/段
// 單段請求逾時:超過即報錯(觸發重試),不讓 stalled 上傳無聲卡死。
const GROQ_FETCH_TIMEOUT_MS = 120000;
// 單段上傳逾時/斷線時的自動重試次數(慢/不穩的上傳常一次就過)。
const GROQ_CHUNK_RETRIES = 3;

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

// Phase A garbled-detection thresholds. SSoT is dict/qaqc_config.json (shared with
// CLI SRT/qaqc_srt.py). Defaults below keep isGarbled() working before the fetch
// resolves and under file:// where the fetch is blocked.
let QAQC_CFG = {
    cjk_ratio_min: 0.25,
    min_chars_for_ratio_check: 10,
    noise_char_max: 1,
    long_latin_cjk_ratio_max: 0.5,
    noise_chars: '┌┐└┘├┤┬┴┼│─⊇◡◬Ⓓ჏ს⓪①②③④⑤⑥⑦⑧⑨',
};

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
        const [typo, prefixes, qaqcCfg] = await Promise.all([
            mod.loadTypoDict(ACTIVE_DOMAIN),
            mod.loadHallucinationPrefixes(),
            mod.loadQaqcConfig(),
        ]);
        TYPO_FIXES = typo;
        HALLUCINATION_PREFIXES = prefixes;
        if (qaqcCfg && Object.keys(qaqcCfg).length) QAQC_CFG = { ...QAQC_CFG, ...qaqcCfg };
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
    // 圖文版好學生筆記 PNG(若有產出)→ images/
    if (imageNotesPngs.length) {
        const idn = ($('identity-input') && $('identity-input').value.trim()) || 'notes';
        const imgFolder = folder.folder('images');
        imageNotesPngs.forEach((p, i) =>
            imgFolder.file(`good_student_notes_${idn}_p${String(i + 1).padStart(2, '0')}.png`, p.base64, { base64: true }));
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
            language_mode: ($('lang-select') ? $('lang-select').value : 'auto'),
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
            image_notes: imageNotesPngs.length
                ? { engine: 'gemini-2.5-flash-image', identity: identity || 'notes', pages: imageNotesPngs.length, dir: 'images/' }
                : null,
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

function isGarbled(text, mode) {
    // Rules: see prompts/qaqc_core_rules.md § R1.2.
    // 語言感知:mode='en' 走「拉丁比例過低=亂碼」分支(見下);其餘(zh)維持原 CJK 規則,
    // 與 CLI qaqc_srt.py 仍互為鏡像。英文場若用原 CJK 規則會把整篇英文當亂碼全砍。
    // Previously `length < 2 → true`, which silently dropped valid single-char
    // Chinese replies like "對", "嗯". Relaxed to empty-only.
    if (!text) return true;
    const cjkRe = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef，。！？、；：「」『』（）《》〈〉—…·～]/g;
    const cjkCount = (text.match(cjkRe) || []).length;
    const totalNonSpace = text.replace(/\s/g, '').length;
    if (totalNonSpace === 0) return true;
    if (mode === 'en') {
        // 英文逐字稿:拉丁字母(含 À-ɏ 重音,屬正常人名)比例過低 → 亂碼。
        // 混入的整段 CJK/西里爾幻覺會因拉丁比例≈0 一併被涵蓋。不套用下方 CJK 規則。
        if (/[�]/.test(text)) return true;
        const latin = (text.match(/[A-Za-zÀ-ɏ]/g) || []).length;
        return (latin / totalNonSpace) < QAQC_CFG.cjk_ratio_min
            && totalNonSpace > QAQC_CFG.min_chars_for_ratio_check;
    }
    const cjkRatio = cjkCount / totalNonSpace;
    if (cjkRatio < QAQC_CFG.cjk_ratio_min && totalNonSpace > QAQC_CFG.min_chars_for_ratio_check) return true;
    if (/[\ufffd]/.test(text)) return true;
    const noiseEsc = (QAQC_CFG.noise_chars || '').replace(/[.*+?^${}()|[\]\\-]/g, '\\$&');
    const noiseRe = noiseEsc ? new RegExp(`[${noiseEsc}]`, 'g') : null;
    if (noiseRe && (text.match(noiseRe) || []).length > QAQC_CFG.noise_char_max) return true;
    const exoticRe = /[\u10a0-\u10ff\u0600-\u06ff\u0400-\u04ff\u0e00-\u0e7f\u0900-\u097f]/g;
    if ((text.match(exoticRe) || []).length > 0) return true;
    const longLatinRun = /(?:[a-zA-Z]{2,}\s+){5,}/;
    if (longLatinRun.test(text) && cjkRatio < QAQC_CFG.long_latin_cjk_ratio_max) return true;
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

// ── 大檔壓縮路徑:decode → 16kHz mono → MP3(64kbps),取代未壓縮 WAV ──
// 21 分鐘 WAV ≈ 41MB;同樣音訊 64kbps MP3 ≈ 10MB,可一次直送 Groq、上傳超快。
// 需要 lamejs(studio.html CDN 載入);不可用時呼叫端會自動退回 fileToChunks(WAV)。

function encodePcmToMp3(int16, sampleRate) {
    if (typeof lamejs === 'undefined' || !lamejs.Mp3Encoder) {
        throw new Error('lamejs 未載入');
    }
    const enc = new lamejs.Mp3Encoder(1, sampleRate, 64); // mono, 64kbps
    const block = 1152;
    const parts = [];
    for (let i = 0; i < int16.length; i += block) {
        const buf = enc.encodeBuffer(int16.subarray(i, i + block));
        if (buf.length > 0) parts.push(new Uint8Array(buf));
    }
    const end = enc.flush();
    if (end.length > 0) parts.push(new Uint8Array(end));
    return new Blob(parts, { type: 'audio/mpeg' });
}

async function fileToMp3Segments(file) {
    if (typeof lamejs === 'undefined' || !lamejs.Mp3Encoder) {
        throw new Error('lamejs 未載入');
    }
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuf = await ctx.decodeAudioData(await file.arrayBuffer());
    await ctx.close();
    const SR = 16000;
    const off = new OfflineAudioContext(1, Math.ceil(audioBuf.duration * SR), SR);
    const src = off.createBufferSource();
    src.buffer = audioBuf;
    src.connect(off.destination);
    src.start(0);
    const mono = await off.startRendering();
    const ch = mono.getChannelData(0);
    const int16 = new Int16Array(ch.length);
    for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    // 每段 MP3 控制在 ~20MB 以下(64kbps mono = 8KB/秒 → ~2400 秒/段)。
    // ≤ ~40 分鐘的演講會壓成「1 段」→ 單次直送、不需切段。
    const SEG_SEC = 2400;
    const segSamples = SEG_SEC * SR;
    const nSeg = Math.max(1, Math.ceil(int16.length / segSamples));
    const jobs = [];
    for (let s = 0; s < nSeg; s++) {
        const slice = int16.subarray(s * segSamples, Math.min((s + 1) * segSamples, int16.length));
        const blob = encodePcmToMp3(slice, SR);
        jobs.push({ blob, timeOffset: s * SEG_SEC, filename: 'audio.mp3', bytes: blob.size });
    }
    return { jobs, duration: mono.duration };
}

// ─────────────────────────────────────────────────────────
//  Groq Whisper API
// ─────────────────────────────────────────────────────────

// Build the Whisper prompt for a given language mode. Groq prompt 上限 896 字元。
// - 'auto':中性 —— 不宣稱任何語言(否則會把自動偵測帶偏),只把使用者 context 當提示詞
// - 'zh' / 'en':宣稱語言 + 對應語系的 context 框架
function buildGroqPrompt(language, contextPrompt) {
    const maxLen = 896;
    if (language === 'auto') {
        return contextPrompt ? contextPrompt.slice(0, maxLen) : '';
    }
    const profiles = {
        zh: { base: '這是一段繁體中文錄音。', pre: ' 內容包含：', suf: '。' },
        en: { base: 'This is an English-language recording of a talk or meeting.', pre: ' Key terms: ', suf: '.' },
    };
    const p = profiles[language] || profiles.zh;
    if (!contextPrompt) return p.base;
    const prefix = `${p.base}${p.pre}`;
    const budget = maxLen - prefix.length - p.suf.length;
    const trimmed = budget > 0 ? contextPrompt.slice(0, budget) : '';
    return `${prefix}${trimmed}${p.suf}`;
}

async function callGroqWhisper(audioBlob, apiKey, contextPrompt, filename, language) {
    const lang = language || 'auto';
    const finalPrompt = buildGroqPrompt(lang, contextPrompt);
    const fd = new FormData();
    // Direct-send path passes the real filename so Groq detects the format;
    // chunk fallback passes WAV blobs as 'audio.wav'.
    fd.append('file', audioBlob, filename || 'audio.wav');
    fd.append('model', 'whisper-large-v3');
    fd.append('response_format', 'verbose_json');
    // 'auto' → 不送 language,讓 Whisper 自動偵測音檔語言、忠實轉出原文。
    // 翻譯永遠是之後的獨立步驟(原則 2),絕不在轉錄階段讓 Groq 順手翻。
    if (lang !== 'auto') fd.append('language', lang);
    fd.append('temperature', '0.0');
    if (finalPrompt) fd.append('prompt', finalPrompt);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), GROQ_FETCH_TIMEOUT_MS);
    let resp;
    try {
        resp = await fetch(GROQ_URL, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${apiKey}` },
            body: fd,
            signal: controller.signal,
        });
    } catch (err) {
        if (err.name === 'AbortError') {
            throw new Error(`Groq 請求逾時(${GROQ_FETCH_TIMEOUT_MS / 1000} 秒未回應),可能網路不穩或該段過大`);
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
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
    const generationConfig = { temperature: 0.2, maxOutputTokens: 65536 };
    // 校稿/補充/筆記都是格式化任務,不需要思考。Gemini 2.5 thinking token 與輸出
    // 共用 maxOutputTokens,長逐字稿時 thinking 會吃掉額度導致正文被截斷 → 違反零省略。
    // flash 支援 thinkingBudget:0 完全關閉;pro 不可設 0,故僅對 flash 套用。
    if (model.includes('flash')) {
        generationConfig.thinkingConfig = { thinkingBudget: 0 };
    }
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig,
        }),
    });
    if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(`Gemini ${resp.status} [${model}]: ${errText.substring(0, 200)}`);
    }
    const data = await resp.json();
    if (data.usageMetadata) {
        recordGeminiTokens(model, data.usageMetadata.promptTokenCount, data.usageMetadata.candidatesTokenCount);
    }
    // 防呆:安全機制攔截、被截斷或無 parts 時給友善訊息,而非 TypeError。
    const cand = data.candidates && data.candidates[0];
    if (!cand) {
        const block = data.promptFeedback && data.promptFeedback.blockReason;
        throw new Error(`Gemini ${model}: 無回傳內容${block ? ` (prompt 被擋:${block})` : ' (可能被安全機制攔截)'}`);
    }
    const parts = cand.content && cand.content.parts;
    const text = parts ? parts.map(p => p.text || '').join('') : '';
    if (!text) {
        throw new Error(`Gemini ${model}: 回傳無文字內容 (finishReason=${cand.finishReason || '?'})`);
    }
    return text;
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
    const language = $('lang-select') ? $('lang-select').value : 'auto';
    if (!file) return alert('請先上傳音訊檔案');
    if (!apiKey) return alert('請輸入 Groq API Key');

    const btn = $('btn-transcribe');
    btn.disabled = true;
    showProgress(1);

    try {
        const allSegments = [];
        const sizeMB = (file.size / 1024 / 1024).toFixed(1);
        const langLabel = { auto: '自動偵測', zh: '中文(強制)', en: 'English(強制)' }[language] || language;
        addProgressLine(1, `🌐 轉錄語言:${langLabel}`, 'ok');
        let duration = 0;

        if (file.size <= GROQ_MAX_DIRECT_BYTES) {
            // ── 小檔直送:Groq 原生收 mp3/m4a/mp4/wav…,一次回傳就有正確全域時間戳。
            //    不解碼、不重採樣、不手動拼時間軸。 ──
            addProgressLine(1, `⏳ 直接上傳原檔 (${sizeMB}MB) 至 Groq...`, 'run');
            setProgressBar(1, 20);
            const result = await callGroqWhisper(file, apiKey, context, file.name, language);
            let idx = 1;
            for (const seg of (result.segments || [])) {
                const text = (seg.text || '').trim();
                if (!text) continue;
                allSegments.push({ idx: idx++, start: seg.start, end: seg.end, text });
            }
            duration = allSegments.length ? allSegments[allSegments.length - 1].end : 0;
            setProgressBar(1, 90);
        } else {
            // ── 大檔:超過 Groq 單次上限,需切段。優先「壓成 MP3」(64kbps,上傳量小);
            //    lamejs 不可用時自動退回「WAV 切段」(較大、上傳慢但可用)。
            //    兩條路都產出統一的 jobs = [{blob, timeOffset, filename}],後面同一個迴圈上傳。 ──
            let jobs, segLabel;
            try {
                addProgressLine(1, `⏳ 檔案 ${sizeMB}MB 超過上限,壓縮成 MP3(16kHz mono 64kbps)...`, 'run');
                const r = await fileToMp3Segments(file);
                jobs = r.jobs;
                duration = r.duration;
                segLabel = '壓縮+轉錄';
                const mb = (jobs.reduce((a, j) => a + j.bytes, 0) / 1024 / 1024).toFixed(1);
                addProgressLine(1, `✓ 已壓成 MP3:${jobs.length} 段,共約 ${mb}MB(原檔 ${sizeMB}MB)`, 'ok');
            } catch (e) {
                addProgressLine(1, `⚠ MP3 壓縮不可用(${e.message}),改用 WAV 切段`, 'fail');
                const c = await fileToChunks(file);
                duration = c.duration;
                jobs = c.chunks.map((blob, i) => ({ blob, timeOffset: i * CHUNK_DURATION, filename: 'audio.wav', bytes: blob.size }));
                segLabel = '轉錄';
                addProgressLine(1, `✓ 時長 ${Math.round(duration)}秒，${jobs.length} 段(WAV)`, 'ok');
            }
            setProgressBar(1, 10);

            let globalIdx = 1;
            for (let i = 0; i < jobs.length; i++) {
                addProgressLine(1, `⏳ ${segLabel} ${i+1}/${jobs.length} ...`, 'run');
                // 慢/不穩的上傳:逾時或網路中斷時自動重試(最多 GROQ_CHUNK_RETRIES 次)。
                // 401/4xx 等金鑰/請求錯誤不重試(重試也沒用)→ 直接拋出。
                let result = null;
                for (let attempt = 1; attempt <= GROQ_CHUNK_RETRIES; attempt++) {
                    try {
                        result = await callGroqWhisper(jobs[i].blob, apiKey, context, jobs[i].filename, language);
                        break;
                    } catch (err) {
                        const retriable = /逾時|Failed to fetch|NetworkError|network|aborted/i.test(err.message);
                        if (retriable && attempt < GROQ_CHUNK_RETRIES) {
                            addProgressLine(1, `⚠ 第 ${i+1} 段第 ${attempt} 次逾時/中斷,重試中...`, 'fail');
                            await sleep(2000);
                            continue;
                        }
                        throw err;
                    }
                }
                if (result && result.segments) {
                    for (const seg of result.segments) {
                        const text = (seg.text || '').trim();
                        if (!text) continue;
                        allSegments.push({
                            idx: globalIdx++,
                            start: seg.start + jobs[i].timeOffset,
                            end: seg.end + jobs[i].timeOffset,
                            text,
                        });
                    }
                }
                addProgressLine(1, `✓ 片段 ${i+1} 完成`, 'ok');
                setProgressBar(1, 10 + 80 * ((i+1) / jobs.length));
            }
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

    // Filter garbled — 語言感知。依 Step 1 的語言選擇;'auto' 時用整篇 CJK 比例自動判斷。
    let mode = $('lang-select') ? $('lang-select').value : 'auto';
    if (mode === 'auto') {
        const allText = phase1.join('');
        const nonSpace = allText.replace(/\s/g, '').length || 1;
        const cjk = (allText.match(/[一-鿿㐀-䶿]/g) || []).length;
        mode = (cjk / nonSpace) >= 0.5 ? 'zh' : 'en';
    }
    addProgressLine(stepN, `🔍 亂碼判定模式:${mode === 'en' ? '英文(拉丁)' : '中文'}`, 'ok');
    let phase2 = [];
    for (const t of phase1) {
        if (isGarbled(t, mode)) { removedG++; continue; }
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
    // 輸出語言:'source' → 同語言校稿;'zh-TW' → 合併「忠實翻譯 + 校稿」一次完成。
    // cleaned.md 本就丟時間軸,故翻譯不違反原則 2;零省略改用 1:1 段落對齊驗證(E3)。
    const outLang = $('out-lang-select') ? $('out-lang-select').value : 'source';
    const translate = outLang === 'zh-TW';

    const ctxInput = ($('context-input') ? $('context-input').value : '').trim();
    const ctxBlock = ctxInput
        ? `\n## 領域背景(使用者當下提供,供專名校正參考)\n${ctxInput}\n`
        : '';

    const srcSegs = rawText.split('\n').filter(l => l.trim()).length;
    const model = $('gemini-model') ? $('gemini-model').value : 'gemini-2.5-flash';

    let prompt;
    if (translate) {
        addProgressLine(stepN, '── Phase B：忠實翻譯成繁體中文 + 校稿 ──', 'run');
        prompt = `你是一位專業的逐字稿譯者兼校稿員。請將以下逐字稿**忠實翻譯成繁體中文**,同時完成校稿。

## 翻譯 + 校稿鐵律(務必遵守)
1. **零省略**:原文每一句都必須翻譯,嚴禁摘要、濃縮、刪減,嚴禁改寫成「講者提到…」這類第三人稱描述。保留第一人稱原話與語氣。
2. **1:1 對齊**:逐段對應翻譯,譯文語意單位數量應與原文一致,不可合併或砍掉原文段落。原文約 ${srcSegs} 個句段。
3. **專名保留**:人名、產品名、技術名維持原文(如 Claude、Anthropic、MCP、Opus),不要硬翻;其餘忠實譯為自然的繁體中文。
4. 補上中文標點與接續詞、合併破碎斷行、依語意分段;可在段落之間插入 Markdown 標題(標題另起一行,不可取代原文內容)。
5. 輸出**只有翻譯後的繁體中文 Markdown**,不要附原文、不要加譯註或說明。
${ctxBlock}
## 原始逐字稿(${rawText.length} 字)
${rawText}`;
    } else {
        addProgressLine(stepN, '── Phase B：AI 校稿 ──', 'run');
        const r2Rules = rulesSection('## R2. Phase B 校稿核心鐵律', '## R3.') || `
### 必須做的事:
1. 補上標點符號、接續詞、合併破碎斷行、依語意分段、插入 Markdown 標題
### 嚴禁:
- 嚴禁刪減、濃縮、摘要、改語氣、第三人稱描述、省略細節
### 字數檢查:
- 輸出字數必須落在輸入 95%-105% 之間`;
        const r7Rules = rulesSection('## R7. Phase C', '## R8.') || `
### Phase C 冒號:把「前指引導語(…是/就是/說/講說、概念名詞標頭、講者名、例如/換句話說)」後的逗號/句號改全形冒號「：」,並把半形標點全形化。`;
        const r8Rules = rulesSection('## R8. Phase D', '## 引用方式') || `
### Phase D 通順:在話題轉換/舉例/回扣前文/進入下一點的接縫,優先補「內容指涉型 hook」(回指/框架/轉折/列點/過場/復述/收束),零省略、不刪改原句。`;
        prompt = `你是一位逐字稿校稿專家。請對以下語音轉錄的原始文字進行校稿。

${r2Rules}

## 標點正規化(Phase C,§ R7)
${r7Rules}

## 通順 / hook(Phase D,§ R8)
${r8Rules}
${ctxBlock}
## 原始逐字稿(${rawText.length} 字)
${rawText}`;
    }

    cleanedMd = await callGeminiWithRetry(prompt, apiKey, stepN, model);

    if (translate) {
        // 跨語言:字數比失效,改報「原文句段數 vs 譯文段落數」供對齊判斷,並對嚴重落差告警。
        const outParas = cleanedMd.split('\n').filter(l => l.trim() && !/^#{1,6}\s/.test(l.trim())).length;
        addProgressLine(stepN, `✓ 翻譯 + 校稿完成 (${cleanedMd.length} 字;原 ${srcSegs} 句段 → 譯 ${outParas} 段)`, 'ok');
        if (cleanedMd.length < rawText.length * 0.25) {
            addProgressLine(stepN, `⚠ 譯文明顯偏短,可能有省略,請用「編輯原文」分頁核對`, 'fail');
        }
    } else {
        const ratio = cleanedMd.length / rawText.length;
        if (ratio < 0.9) {
            addProgressLine(stepN, `⚠ 警告：輸出 ${cleanedMd.length} 字，僅為原文 ${Math.round(ratio*100)}%，可能有省略`, 'fail');
        }
        addProgressLine(stepN, `✓ Phase B 完成 (${cleanedMd.length} 字)`, 'ok');
    }
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
            // No Gemini, just use raw cleaned text with basic paragraph merge.
            // 翻譯需要 LLM,僅清理模式無法翻譯 → 提示使用者。
            if (($('out-lang-select') ? $('out-lang-select').value : 'source') === 'zh-TW') {
                addProgressLine(2, '⚠ 「翻譯成繁體中文」需 AI 校稿;僅清理模式維持原文', 'fail');
            }
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
//  Step 4 圖文版:底圖=html2canvas 確定性渲染(文字保真),Gemini 只疊視角手寫註解。
//  設計 SSoT: prompts/image_notes_design.md(Stage B 規則 + 6 色語義系統)。
//  P3,僅 Web+Antigravity 可驅動(影像 API 需 user key,見 CLAUDE.md 原則 5)。
// ─────────────────────────────────────────────────────────

// 把 md 建成離屏 A4 白底容器(真 DOM,文字零遺漏)。回傳 host 與分頁資訊;用完要 remove。
function buildA4Host(md) {
    if (typeof html2canvas === 'undefined') throw new Error('html2canvas 未載入');
    const A4W = 794, A4H = 1123, PAD = 56;  // 96dpi A4 + 邊距
    const host = document.createElement('div');
    host.className = 'gsn-host';
    host.style.cssText = `position:absolute;left:-99999px;top:0;width:${A4W}px;background:#ffffff;`
        + `color:#333;padding:${PAD}px;box-sizing:border-box;`
        + `font-family:'Noto Sans TC',sans-serif;font-size:16px;line-height:1.85;`;
    host.innerHTML = marked.parse(md || '');
    host.querySelectorAll('h1,h2,h3').forEach(h => { h.style.color = '#1a1a1a'; });
    host.querySelectorAll('blockquote').forEach(b => {
        b.style.cssText = 'border-left:3px solid #5a5;margin:1em 0;padding:6px 12px;background:#f3f8f3;color:#444;';
    });
    document.body.appendChild(host);
    const nPages = Math.max(1, Math.ceil(host.scrollHeight / A4H));
    const plain = host.innerText || md || '';
    return { host, A4W, A4H, nPages, plain };
}

// 擷取 host 的第 index 頁(A4 高)為 PNG。
async function captureA4Page(host, index, A4W, A4H) {
    const canvas = await html2canvas(host, {
        backgroundColor: '#ffffff', scale: 2,
        width: A4W, height: A4H, x: 0, y: index * A4H,
        windowWidth: A4W, scrollX: 0, scrollY: 0, useCORS: true,
    });
    const dataUrl = canvas.toDataURL('image/png');
    return { dataUrl, base64: dataUrl.split(',')[1] };
}

// 註解規劃器:免費文字模型(gemini-2.5-flash)只決定「要標什麼」,回嚴格 JSON。不打付費影像 API。
async function getPageAnnotations(pageText, identity, apiKey) {
    const model = 'gemini-2.5-flash';
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
    const prompt = `你是「好學生筆記」的批註規劃器。針對以下這一頁課程內容,以「${identity}」的視角,決定要在頁面上加哪些手寫批註。
只輸出 JSON(不要任何其他文字),結構:
{
 "highlights": ["要用黃色螢光標的短句(原文一字不差出現)"],
 "keyterms":   ["要用藍色圈選的關鍵詞(原文一字不差出現)"],
 "marks":      [{"anchor":"原文片段(一字不差)","kind":"insight 或 question","text":"很短的旁註"}],
 "sidenotes":  [{"anchor":"原文片段(一字不差,標示便利貼貼在哪段)","color":"orange 或 green","text":"用${identity}視角的生活化類比/連結,一句話"}],
 "insight":    "底部核心洞察一句,用${identity}的語言總結"
}
規則:
- highlights / keyterms / 各 anchor 必須是原文裡『一字不差』出現的片段(程式要用它定位,不可改寫或翻譯)。
- highlights 2-4 個、keyterms 2-5 個、marks 1-3 個、sidenotes 2-3 個。
- sidenotes 用「${identity}」的日常情境做類比(例如買菜媽媽就用挑菜、預算、路線來比喻)。

## 本頁原文
${(pageText || '').slice(0, 4000)}`;
    const resp = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.4, maxOutputTokens: 2048, thinkingConfig: { thinkingBudget: 0 }, responseMimeType: 'application/json' },
        }),
    });
    if (!resp.ok) {
        const t = await resp.text();
        throw new Error(`註解規劃 ${resp.status}: ${t.slice(0, 160)}`);
    }
    const data = await resp.json();
    const cand = data.candidates && data.candidates[0];
    const txt = (cand && cand.content && cand.content.parts) ? cand.content.parts.map(p => p.text || '').join('') : '';
    if (!txt) throw new Error('註解規劃:回傳空白(可能被安全機制攔截)');
    try { return JSON.parse(txt); }
    catch {
        const m = txt.match(/\{[\s\S]*\}/);
        if (m) { try { return JSON.parse(m[0]); } catch { /* fall through */ } }
        throw new Error('註解規劃:JSON 解析失敗');
    }
}

// 只把「第一個」符合 phrase 的 text node 片段包成 span,只動該片段、其餘原文不碰。
function _wrapFirstMatch(root, phrase, className) {
    if (!phrase || phrase.length < 2) return false;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        if (node.parentElement && node.parentElement.closest('.postit-orange,.postit-green,.insight-box,.kw-blue,.hl-yellow')) continue;
        const idx = node.textContent.indexOf(phrase);
        if (idx < 0) continue;
        const before = node.textContent.slice(0, idx);
        const after = node.textContent.slice(idx + phrase.length);
        const span = document.createElement('span');
        span.className = className;
        span.textContent = node.textContent.slice(idx, idx + phrase.length);
        const frag = document.createDocumentFragment();
        if (before) frag.appendChild(document.createTextNode(before));
        frag.appendChild(span);
        if (after) frag.appendChild(document.createTextNode(after));
        node.parentNode.replaceChild(frag, node);
        return true;
    }
    return false;
}

function _findBlockWithText(root, phrase) {
    if (!phrase) return null;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        if (node.textContent.includes(phrase)) {
            return node.parentElement && (node.parentElement.closest('p,li,h1,h2,h3,blockquote') || node.parentElement);
        }
    }
    return null;
}

// 把註解 JSON 決定性地疊到 host DOM(純 DOM/CSS,無 AI、無隨機 → 每頁風格一致)。
// 找不到 anchor 的註解就略過,絕不改動原文。
function applyAnnotationsToDom(host, ann, identity) {
    ann = ann || {};
    (ann.keyterms || []).forEach(t => _wrapFirstMatch(host, String(t).trim(), 'kw-blue'));
    (ann.highlights || []).forEach(h => _wrapFirstMatch(host, String(h).trim(), 'hl-yellow'));
    (ann.marks || []).forEach(m => {
        const blk = _findBlockWithText(host, ((m && m.anchor) || '').trim());
        if (!blk) return;
        const span = document.createElement('span');
        span.className = 'mark-red';
        span.textContent = ` ${m.kind === 'question' ? '?' : '!'}${m.text ? ' ' + m.text : ''}`;
        blk.appendChild(span);
    });
    (ann.sidenotes || []).forEach(s => {
        const blk = _findBlockWithText(host, ((s && s.anchor) || '').trim());
        const note = document.createElement('div');
        note.className = (s && s.color === 'green') ? 'postit-green' : 'postit-orange';
        note.textContent = (s && s.text) || '';
        if (blk && blk.parentNode) blk.parentNode.insertBefore(note, blk.nextSibling);
        else host.appendChild(note);
    });
    if (ann.insight) {
        const box = document.createElement('div');
        box.className = 'insight-box';
        box.textContent = `💡 核心洞察:${ann.insight}`;
        host.appendChild(box);
    }
}

// 依 image_notes_design.md Stage B 規則組 prompt:只疊加、不改寫原文。
function buildImageNotesPrompt(identity, pageText) {
    return `這是一張白底的課程筆記頁(印刷文字)。請把它轉成「好學生筆記」:在**保留原始印刷文字完全不變**的前提下,於其上疊加手寫風格的彩色註解。

## 鐵律
- **絕對不要改寫、重排、翻譯或重新生成原本的印刷文字**;原文必須清晰可辨、位置不動。你只是在它上面「手寫畫記」。
- 用「${identity}」的專業視角,針對頁面上**實際出現**的內容做類比與補充,不要憑空捏造頁面上沒有的東西。

## 註解規則(手寫風格,見專案 6 色語義系統)
- 🔵 藍色(#1976D2):圈選關鍵術語、底線重要句子。
- 🔴 紅色(#D32F2F):「!」標記洞察、「?」標記疑問。
- 🟠 橘色(#E65100)/🟢 綠色(#388E3C):在邊欄用「${identity}」的術語做專業類比、便利貼(post-it)區塊、簡單箭頭/流程示意。
- 🟡 黃色半透明:螢光筆標記重點句。
- 底部加一個「💡 核心洞察」手寫框:用「${identity}」的語言總結並連結到其實際工作。

## 本頁文字(供你理解內容、做精準類比;勿據此重畫文字)
${(pageText || '').slice(0, 4000)}

輸出:一張在原頁面上疊好手寫註解的圖片。`;
}

// 呼叫 gemini-2.5-flash-image(banana):輸入底圖 + prompt → 回傳疊註解後的影像 base64。
async function callGeminiImage(promptText, baseImageBase64, apiKey) {
    const model = 'gemini-2.5-flash-image';
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [
                { text: promptText },
                { inline_data: { mime_type: 'image/png', data: baseImageBase64 } },
            ] }],
            generationConfig: { responseModalities: ['IMAGE'] },
        }),
    });
    if (!resp.ok) {
        const errText = await resp.text();
        if (resp.status === 429) {
            throw new Error('Gemini image 429:此 API key 沒有 gemini-2.5-flash-image(影像/付費模型)的額度。'
                + '影像生成是付費模型(約 $0.039/張),免費方案通常無額度 → 需在 Google AI Studio/Cloud 為該專案啟用計費,'
                + '或改用已啟用計費的 key。(文字模型免費可用,影像模型不行,是兩種額度)');
        }
        throw new Error(`Gemini image ${resp.status}: ${errText.substring(0, 200)}`);
    }
    const data = await resp.json();
    if (data.usageMetadata) {
        recordGeminiTokens(model, data.usageMetadata.promptTokenCount, data.usageMetadata.candidatesTokenCount);
    }
    const cand = data.candidates && data.candidates[0];
    if (!cand) {
        const block = data.promptFeedback && data.promptFeedback.blockReason;
        throw new Error(`Gemini image: 無回傳${block ? ` (prompt 被擋:${block})` : ' (可能被安全機制攔截)'}`);
    }
    const parts = (cand.content && cand.content.parts) || [];
    const imgPart = parts.find(p => p.inlineData || p.inline_data);
    const inline = imgPart && (imgPart.inlineData || imgPart.inline_data);
    if (!inline || !inline.data) {
        const t = parts.map(p => p.text || '').join(' ').slice(0, 200);
        throw new Error(`Gemini image: 回傳無影像 (finishReason=${cand.finishReason || '?'}${t ? '; ' + t : ''})`);
    }
    return inline.data;
}

async function runImageNotes() {
    const identity = $('identity-input').value.trim();
    const apiKey = getGeminiKey();
    const source = enhancedMd || cleanedMd;
    if (!identity) return alert('請先輸入你的專業身份(上方欄位)');
    if (!apiKey) return alert('請先在 Step 2 輸入 Gemini API Key');
    if (!source) return alert('沒有可用的內容,請先完成 Step 2/3');
    if (typeof html2canvas === 'undefined') return alert('html2canvas 未載入,無法渲染底圖');

    const btn = $('btn-image-notes');
    btn.disabled = true;
    imageNotesPngs = [];
    $('res-img-gallery').innerHTML = '';
    showProgress('img');

    let built = null;
    try {
        addProgressLine('img', '⏳ 渲染 A4 白底底圖(真文字,零遺漏)...', 'run');
        setProgressBar('img', 15);
        built = buildA4Host(source);
        // 預載手寫字體,確保 html2canvas 擷取到 Long Cang 而非 fallback。
        if (document.fonts && document.fonts.load) {
            try { await document.fonts.load("16px 'Long Cang'"); await document.fonts.ready; } catch { /* 略 */ }
        }
        addProgressLine('img', `✓ 底圖就緒(原稿約 ${built.nPages} 頁;本輪測試只做第 1 頁)`, 'ok');

        // 測試階段:只做第 1 頁。測通後把 PAGES 改成 built.nPages 即跑全部頁(同一套 CSS → 天然一致)。
        const PAGES = 1;
        const per = Math.ceil(built.plain.length / built.nPages);
        const gallery = $('res-img-gallery');
        for (let i = 0; i < PAGES; i++) {
            const pageText = built.plain.slice(i * per, (i + 1) * per);
            addProgressLine('img', `⏳ 第 ${i + 1}/${PAGES} 頁:免費文字模型規劃「${identity}」視角批註...`, 'run');
            setProgressBar('img', 20 + 50 * (i / PAGES));
            let ann = null;
            try {
                ann = await getPageAnnotations(pageText, identity, apiKey);
            } catch (e) {
                addProgressLine('img', `⚠ 批註規劃失敗(${e.message}),本頁僅出乾淨底圖`, 'fail');
            }
            if (ann) {
                applyAnnotationsToDom(built.host, ann, identity);
                addProgressLine('img', '✓ 批註已疊上(藍圈 / 黃螢光 / 紅 !? / 便利貼 / 💡 洞察)', 'ok');
            }
            addProgressLine('img', `⏳ 第 ${i + 1} 頁:渲染成 PNG...`, 'run');
            const cap = await captureA4Page(built.host, i, built.A4W, built.A4H);
            imageNotesPngs.push({ dataUrl: cap.dataUrl, base64: cap.base64, identity, index: i });
            const img = document.createElement('img');
            img.src = cap.dataUrl;
            img.alt = `好學生筆記(${identity}視角)第 ${i + 1} 頁`;
            img.style.cssText = 'width:100%;border:1px solid #2a2a2a;border-radius:3px;';
            gallery.appendChild(img);
            addProgressLine('img', `✓ 第 ${i + 1} 頁完成`, 'ok');
        }
        setProgressBar('img', 100);
        $('res-img-stat').textContent = `${imageNotesPngs.length} 頁 · ${identity}視角 · CSS 一致渲染`;
        showResult('img');
    } catch (err) {
        addProgressLine('img', `✗ ${err.message}`, 'fail');
    } finally {
        if (built && built.host && built.host.parentNode) built.host.parentNode.removeChild(built.host);
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
    $('btn-dl-srt').addEventListener('click', () => downloadFile('transcript.srt', srtContent));
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
    $('btn-dl-md1').addEventListener('click', () => { syncStep2Edits(); downloadFile('cleaned.md', cleanedMd); });
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

    // ── Step 4 圖文版 ──
    const identityEcho = $('img-identity-echo');
    if ($('identity-input') && identityEcho) {
        $('identity-input').addEventListener('input', () => {
            identityEcho.textContent = ($('identity-input').value.trim() || '你的身份');
        });
    }
    const imgBtn = $('btn-image-notes');
    if (imgBtn) imgBtn.addEventListener('click', runImageNotes);
    const dlImgBtn = $('btn-dl-img');
    if (dlImgBtn) dlImgBtn.addEventListener('click', () => {
        if (!imageNotesPngs.length) return alert('還沒有圖文版可下載');
        const idn = ($('identity-input').value.trim() || 'notes');
        imageNotesPngs.forEach((p, i) => {
            const a = document.createElement('a');
            a.href = p.dataUrl;
            a.download = `good_student_notes_${idn}_p${String(i + 1).padStart(2, '0')}.png`;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
        });
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
        updateStatusBar();
    });
    $('gemini-key-2').addEventListener('change', () => {
        updateStatusBar();
    });

    const modelSelect = $('gemini-model');
    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            updateStatusBar();
        });
    }

    // Initialize status bar, and run after a tiny delay to catch config.local.js autofills
    updateStatusBar();
    setTimeout(updateStatusBar, 100);
    setTimeout(updateStatusBar, 500);

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
