// ─────────────────────────────────────────────────────────
//  dict-loader.js — 共用詞典的瀏覽器端載入器
//
//  與 dict/load.py 同步資料來源(專案根 /dict/*.json)
//  用法:
//      const typo = await loadTypoDict('parenting');          // { wrong: correct, ... }
//      const prefixes = await loadHallucinationPrefixes();    // [ '內容包含：', ... ]
//      const domains = await listDomains();                   // [ 'parenting', ... ]
//
//  Path convention: assume the page is served such that `/dict/*.json` is reachable.
//  Works under both `file://` (for local dev) and HTTP server contexts.
// ─────────────────────────────────────────────────────────

const DICT_BASE_PATHS = [
    '../dict/',   // served from /web/ relative (most common dev + GitHub Pages)
    '/dict/',     // served from project root
    './dict/',    // served same-dir (fallback)
];

// Version stamp discovered from _manifest.json. Used as a cache-busting query
// string so that a git pull → new dict entries → user hard-reload-free.
let _DICT_VERSION = null;

async function _getVersion() {
    if (_DICT_VERSION !== null) return _DICT_VERSION;
    for (const base of DICT_BASE_PATHS) {
        try {
            const res = await fetch(base + '_manifest.json', { cache: 'no-cache' });
            if (res.ok) {
                const j = await res.json();
                _DICT_VERSION = j.version || '';
                return _DICT_VERSION;
            }
        } catch { /* try next */ }
    }
    _DICT_VERSION = '';
    return '';
}

async function fetchJson(filename) {
    const version = await _getVersion();
    const qs = version ? `?v=${encodeURIComponent(version)}` : '';
    let lastErr = null;
    for (const base of DICT_BASE_PATHS) {
        try {
            const res = await fetch(base + filename + qs, { cache: 'no-cache' });
            if (res.ok) return await res.json();
            lastErr = new Error(`${res.status} ${res.statusText} at ${base + filename}`);
        } catch (err) {
            lastErr = err;
        }
    }
    throw new Error(`dict-loader: failed to fetch ${filename}: ${lastErr}`);
}

/**
 * Load the base typo dictionary merged with an optional domain overlay.
 * @param {string|null} domain  e.g. 'parenting' or null for base only
 * @returns {Promise<Object<string,string>>} flat {wrong: correct}
 */
export async function loadTypoDict(domain = null) {
    const base = (await fetchJson('typo_dict.json')).corrections || {};
    if (!domain) return { ...base };

    try {
        const overlay = (await fetchJson(`typo_dict.${domain}.json`)).corrections || {};
        return { ...base, ...overlay };   // overlay wins on conflict
    } catch (err) {
        console.warn(`[dict] domain "${domain}" not available, using base only:`, err.message);
        return { ...base };
    }
}

/**
 * Load the hallucination prefix list.
 * @returns {Promise<string[]>}
 */
export async function loadHallucinationPrefixes() {
    return (await fetchJson('hallucination_prefixes.json')).prefixes || [];
}

/**
 * Best-effort domain list. Browsers can't scan the dict/ dir directly,
 * so we probe a hard-coded manifest. When a new domain is added, list it here too.
 * (Optional: project could ship a dict/_manifest.json to centralize this.)
 * @returns {Promise<string[]>}
 */
export async function listDomains() {
    try {
        const manifest = await fetchJson('_manifest.json');
        return manifest.domains || [];
    } catch {
        // Fallback: known domains
        return ['parenting'];
    }
}
