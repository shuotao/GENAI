/* admin.jsx — 好學生筆記 後台
   ────────────────────────────────────────────────────────────────────────
   保護模型:登入後所有讀寫都由 firestore.rules 的 admins/ 白名單把關。
   前端不做任何「藏起來」式的權限判斷 —— 非白名單帳號拿到的是 Firestore
   的 permission-denied,不是被 CSS 隱藏的畫面。

   資料載入策略:events(17)/subscribers(318)/blockReasons(6)/stats 一次抓完,
   之後全在前端篩選 —— 資料量小,換來零延遲的分眾切換。
   registrations(885 筆)刻意不預載,點開單一人員時才抓,避免無謂讀取。
*/
const { useState, useEffect, useMemo, useCallback, useRef } = React;

const CATS = {
  mcp:       { label: 'MCP 小聚',   tone: 'mcp' },
  slides:    { label: '演講資料',   tone: 'slides' },
  community: { label: '社群申請',   tone: 'community' },
};
// 主站三道書架的 id,色條要沿用它們既定的顏色(見 style.css)。
const SHELVES = new Set(['public', 'seminar', 'reading']);
const tone = (c) => (CATS[c] ? CATS[c].tone : (SHELVES.has(c) ? c : 'other'));
const catLabel = (c) => (CATS[c] ? CATS[c].label : c);

/* ── 工具 ───────────────────────────────────────────────────────────────── */
const ymNow = () => new Date().toISOString().slice(0, 7);

function csvEscape(v) {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadCsv(filename, rows) {
  // BOM:沒有它 Excel 開繁中 CSV 會變亂碼。
  const body = rows.map((r) => r.map(csvEscape).join(',')).join('\r\n');
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ── 分類推導 ───────────────────────────────────────────────────────────────
   subscriber.categories 是匯入當下寫死的冗餘欄位,事後在 EventsTab 改事件
   分類不會回頭更新它 —— 這是原本「改分類、分眾卻沒反映」的根因。
   正確作法是完全不信任那個欄位,每次都從「這個人報過哪些 eventId」+
   「這些 eventId 現在對應到哪個 category」即時算出來,單一事實來源永遠是
   events collection。 */
function effectiveCats(s, eventById) {
  return [...new Set(
    (s.eventIds || []).map((id) => (eventById[id] || {}).category).filter(Boolean)
  )];
}

/* ── 分眾定義 ───────────────────────────────────────────────────────────────
   分眾一律是「對已載入資料的查詢」,不是另一份維護中的名單。
   新增一個事件 → 自動多一個分眾,不需要改這支程式。 */
function buildSegments(events, subs) {
  const eventById = Object.fromEntries(events.map((e) => [e.id, e]));
  const month = ymNow();
  const inMonth = new Set(
    events.filter((e) => e.category === 'mcp' && (e.date || '').startsWith(month)).map((e) => e.id)
  );
  const has = (s, ids) => (s.eventIds || []).some((i) => ids.has(i));
  const byCat = (c) => subs.filter((s) => effectiveCats(s, eventById).includes(c));

  const segs = [
    { id: 'all',       name: '全部聯絡人',              rows: subs },
    { id: 'mcp',       name: 'MCP 歷次報名(累積)',    rows: byCat('mcp') },
    { id: 'mcp-month', name: `MCP 當月報名(${month})`,
      rows: subs.filter((s) => has(s, inMonth)),
      hint: inMonth.size ? null : '本月尚無 MCP 場次,故為空' },
    { id: 'slides',    name: '演講資料獲得名單',        rows: byCat('slides') },
    { id: 'community', name: '社群申請電子報名單',      rows: byCat('community') },
  ];
  // 自訂 category(未來新課程種類)自動長出來
  const known = new Set(Object.keys(CATS));
  [...new Set(events.map((e) => e.category))].filter((c) => c && !known.has(c)).forEach((c) => {
    segs.push({ id: c, name: catLabel(c), rows: byCat(c) });
  });
  // 名單軌跡分眾:「曾出現在哪一份名單上」,不是報名紀錄,因此獨立成一組。
  //
  // 標籤一律從資料現有的 lists[] 枚舉出來,**不寫死白名單** —— 這與上面事件分眾
  // 同一個原則:多一種名單就自動多一個分眾,不必回來改這支程式。
  // 原本寫死「永久收件人/從未出席/手動補入」三個 + 「電子報」前綴,結果
  // 後台手動新增、MCP 1–8 月累積快照、未報名清單、來自黑名單、來自退信清單、
  // 手動補入(第二批)、測試位址 這些標籤全都沒有分眾,
  // 人明明在通訊錄裡卻挑不出來也匯不出來 —— 看起來就像「補進去的名單不見了」。
  const onList = (label) => subs.filter((s) => (s.lists || []).includes(label));

  // 「手動補入」的三種軌跡合併成單一分眾。對匯出而言它們是同一件事 ——
  // 人工加進來的人 —— 拆成三個項目只會逼使用者每次都記得三個都要勾,
  // 漏勾一個就少寄一批。成員取聯集,同時掛在兩批的人自動只算一次。
  //   手動補入          ← GWS supp_audience.txt
  //   手動補入(第二批)  ← GWS 後續批次
  //   後台手動新增      ← 後台按「手動補入聯絡人」加的(AddContact)
  // 合併只發生在「挑選」這一層:原始標籤仍原封留在 subscriber.lists[],
  // 通訊錄展開個人時看得到他是哪一批來的,來源軌跡沒有被抹掉。
  const MANUAL_LABELS = ['手動補入', '手動補入(第二批)', '後台手動新增'];
  const manualRows = subs.filter(
    (s) => (s.lists || []).some((l) => MANUAL_LABELS.includes(l)));
  if (manualRows.length) {
    segs.push({ id: 'list:manual', name: '手動補入', rows: manualRows, group: 'list' });
  }

  // 抑制清單的軌跡合併成單一分眾「黑名單」。黑名單與退信對匯出是同一件事:
  // 這個位址不能寄。分兩項只是在問「他是被手動封的還是寄不出去的」——
  // 那是個人明細該回答的問題,不是挑名單時該分心的事。
  // 「來自退訂清單」刻意不併進來:退訂是當事人自己的意思,與被我方封鎖在
  // 語義與合規上都不同,混在一起會讓「誰主動退訂」永遠問不清楚。
  const SUPPRESS_LABELS = ['來自黑名單', '來自退信清單'];
  const suppressRows = subs.filter(
    (s) => (s.lists || []).some((l) => SUPPRESS_LABELS.includes(l)));
  if (suppressRows.length) {
    segs.push({ id: 'list:suppress', name: '黑名單', rows: suppressRows, group: 'list' });
  }

  // 其餘標籤各自成一個分眾。從未出席釘在前面,電子報那一大群排最後。
  const PINNED = ['從未出席'];
  const rank = (l) => {
    const i = PINNED.indexOf(l);
    return i >= 0 ? i : PINNED.length + (l.startsWith('電子報') ? 1 : 0);
  };
  [...new Set(subs.flatMap((s) => s.lists || []))]
    .filter((l) => !MANUAL_LABELS.includes(l) && !SUPPRESS_LABELS.includes(l))
    .sort((a, b) => rank(a) - rank(b) || String(a).localeCompare(String(b), 'zh-Hant'))
    .forEach((label) => {
      const rows = onList(label);
      if (rows.length) segs.push({ id: 'list:' + label, name: label, rows, group: 'list' });
    });

  segs.push({ id: 'blocked', name: '封鎖區', rows: subs.filter((s) => s.blocked) });
  return segs;
}


/* ── email 正規化 ────────────────────────────────────────────────────────────
   必須與 import_roster.py 產生 document id 的方式一致,否則手動補入會建出
   重複的人。這裡只做「去空白 + 小寫 + .con→.com」——
   email_corrections.json 那份修正表在本機,前端拿不到,也不該拿到:
   它是匯入階段的 SSoT,前端若自己複製一份必然漂移。 */
const EMAIL_RE = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;

function normalizeEmail(v) {
  let raw = String(v || '').trim().toLowerCase();
  if (raw.endsWith('.con')) raw = raw.slice(0, -4) + '.com';
  const m = EMAIL_RE.exec(raw);
  return m ? m[0] : '';
}

/* 手動補入聯絡人。
   對應 GWS 的 supp_audience.txt / extra_permanent_recipients.txt —— 那些人本來就
   不是從報名表來的,而是人工加進名單的,所以這裡一律標上「手動補入」軌跡。
   選了事件才會產生一筆 registration(鐵律 4:名單成員不等於報名紀錄)。 */
function AddContact({ events, existing, onDone, onCancel }) {
  const [f, setF] = useState({ email: '', name: '', eventId: '', note: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const key = normalizeEmail(f.email);
  const dup = key ? existing.find((s) => s.id === key) : null;

  const save = async () => {
    if (!key) { setErr('請填一個看得出來是 email 的位址'); return; }
    setBusy(true); setErr('');
    try {
      const FV = firebase.firestore.FieldValue;
      const ev = events.find((e) => e.id === f.eventId);
      const doc = window.fbDb.collection('subscribers').doc(key);
      const patch = {
        email: key,
        rawEmails: FV.arrayUnion(String(f.email).trim().toLowerCase()),
        // 標籤刻意與 GWS supp_audience.txt 的「手動補入」區隔 —— 那是另一批人,
        // 兩者共用同一個字串會讓「這個人怎麼來的」永遠問不清楚。
        lists: FV.arrayUnion('後台手動新增'),
        source: 'admin-manual',
      };
      // 既有聯絡人不覆蓋既有姓名/備註,只補空的 —— 匯入來的資料比手打的可靠。
      if (f.name.trim() && !(dup && dup.name)) patch.name = f.name.trim();
      if (f.note.trim()) patch.note = f.note.trim();
      if (!dup) {
        patch.blocked = false;
        patch.blockReasons = [];
        patch.tags = [];
        patch.testAddress = false;
        patch.firstSeenAt = new Date().toISOString();
      }
      if (ev) {
        patch.eventIds = FV.arrayUnion(ev.id);
        patch.categories = FV.arrayUnion(ev.category);
        patch.lastSeenAt = new Date().toISOString();
      }
      await doc.set(patch, { merge: true });

      if (ev) {
        const now = new Date().toISOString();
        await doc.collection('registrations').doc(`${ev.id}__manual`).set({
          eventId: ev.id, category: ev.category, eventDate: ev.date || '',
          tickets: ['manual'], ticketsRaw: [f.note.trim() || '後台手動補入'],
          responseId: '', createTime: now, source: 'admin-manual',
        }, { merge: true });
      }
      await onDone();
    } catch (e) { setErr(String((e && e.message) || e)); }
    setBusy(false);
  };

  return (
    <div className="card" style={{ marginBottom: 22, maxWidth: 640 }}>
      <div className="card-title">
        手動補入聯絡人
        <span className="card-meta">不經報名表,直接加進通訊錄</span>
      </div>
      <div className="row" style={{ marginBottom: 10, alignItems: 'flex-start' }}>
        <div className="field" style={{ maxWidth: 280 }}>
          <label className="field-label" htmlFor="ac-email">Email(必填)</label>
          <input id="ac-email" className="inp" placeholder="you@example.com"
                 value={f.email} autoFocus
                 onChange={(e) => setF({ ...f, email: e.target.value })} />
        </div>
        <div className="field" style={{ maxWidth: 160 }}>
          <label className="field-label" htmlFor="ac-name">姓名</label>
          <input id="ac-name" className="inp" placeholder="（選填）"
                 value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
      </div>
      <div className="row" style={{ marginBottom: 10, alignItems: 'flex-start' }}>
        <div className="field" style={{ maxWidth: 280 }}>
          <label className="field-label" htmlFor="ac-event">掛哪個場次</label>
          <select id="ac-event" className="inp" value={f.eventId}
                  onChange={(e) => setF({ ...f, eventId: e.target.value })}>
            <option value="">不掛任何場次(只加進通訊錄)</option>
            {[...events].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
              .map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
        <div className="field" style={{ maxWidth: 160 }}>
          <label className="field-label" htmlFor="ac-note">備註</label>
          <input id="ac-note" className="inp" placeholder="（選填）"
                 value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        </div>
      </div>

      {key && (
        <div className="admin-note" style={{ marginBottom: 12 }}>
          {dup
            ? <>ⓘ <b>{key}</b> 已經在通訊錄裡{dup.name ? `(${dup.name})` : ''}。
                 儲存會<b>合併</b>而不是新增一筆:補上「後台手動新增」軌跡
                 {f.eventId ? '與所選場次' : ''},既有姓名不會被覆蓋。</>
            : <>將以 <b>{key}</b> 建立新聯絡人。</>}
        </div>)}

      <div className="row">
        <button className="btn" onClick={save} disabled={busy || !key}>
          {busy ? '儲存中…' : (dup ? '合併' : '新增')}
        </button>
        <button className="btn ghost" onClick={onCancel}>取消</button>
      </div>
      {err && <div className="err" role="alert">{err}</div>}
    </div>
  );
}


/* ── 封鎖 / 解封二次確認面板 ──────────────────────────────────────────────
   原本是單擊即寫入 Firestore,沒有確認、沒有理由、失敗也不會有任何回饋。
   改成獨立的 inline 面板(不用 window.confirm —— 那個瀏覽器原生對話框會
   卡住整個分頁,手機上尤其糟):
     - 封鎖前必須至少勾一個理由,不然匯出名單時看不出為什麼擋這個人。
     - 解封一個「退訂」的人特別危險 —— 那是當事人主動撤回同意,解封等於
       未經同意又開始寄信給他,因此多一道打勾二次確認。
     - 送出中/失敗都有畫面,不會卡在不知道發生什麼事的狀態。 */
function BlockConfirmPanel({ sub, reasons, onCancel, onConfirm }) {
  const willBlock = !sub.blocked;
  const [picked, setPicked] = useState(() => new Set(sub.blockReasons || []));
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const isUnsub = sub.blocked && (sub.blockReasons || []).includes('unsubscribed');
  const needAck = !willBlock && isUnsub;

  const toggle = (id) => setPicked((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const submit = async () => {
    if (willBlock && !picked.size) { setErr('封鎖前請至少選一個理由'); return; }
    if (needAck && !ack) { setErr('請先勾選下方確認再送出'); return; }
    setBusy(true); setErr('');
    try {
      await onConfirm(sub, willBlock, willBlock ? [...picked] : []);
      onCancel();
    } catch (e) { setErr(String((e && e.message) || e)); }
    setBusy(false);
  };

  return (
    <div className="card" style={{ marginBottom: 22, maxWidth: 520 }}
         role="alertdialog" aria-label={willBlock ? '確認封鎖' : '確認解封'}>
      <div className="card-title">
        {willBlock ? '確認封鎖' : '確認解封'}
        <span className="card-meta">{sub.name || '（無姓名）'} · {sub.email}</span>
      </div>

      {sub.blocked && (
        <p className="admin-note" style={{ marginBottom: 14 }}>
          目前理由:{' '}
          {(sub.blockReasons || []).length
            ? (sub.blockReasons || []).map((r) => (
                <span key={r} className="chip block">
                  {(reasons.find((x) => x.id === r) || {}).label || r}
                </span>))
            : '（無)'}
        </p>
      )}

      {willBlock && (
        <div style={{ marginBottom: 14 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>選擇封鎖理由（至少一個）</div>
          <div className="row">
            {reasons.map((r) => (
              <button key={r.id} type="button"
                      className={'chip block' + (picked.has(r.id) ? '' : ' chip-off')}
                      aria-pressed={picked.has(r.id)}
                      onClick={() => toggle(r.id)}>
                {picked.has(r.id) ? '✓ ' : ''}{r.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {needAck && (
        <label className="admin-note"
               style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 14, color: 'var(--ink-soft)' }}>
          <input type="checkbox" checked={ack}
                 onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 3 }} />
          我確認要解封此人 —— 他先前是<b>主動退訂</b>,解封後會重新收到寄送。
        </label>
      )}

      <div className="row">
        <button className="btn" onClick={submit} disabled={busy} aria-live="polite">
          {busy ? '處理中…' : (willBlock ? '確認封鎖' : '確認解封')}
        </button>
        <button className="btn ghost" onClick={onCancel} disabled={busy}>取消</button>
      </div>
      {err && <div className="err" role="alert">{err}</div>}
    </div>
  );
}

/* ── 迷你走勢圖(inline SVG,不引圖表庫)─────────────────────────────── */
function Spark({ daily }) {
  if (!daily || daily.length < 2) return null;
  const w = 200, h = 34, max = Math.max(...daily.map((d) => d.views), 1);
  const pts = daily.map((d, i) =>
    `${(i / (daily.length - 1)) * w},${h - (d.views / max) * (h - 4) - 2}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} style={{ display: 'block', marginTop: 10 }}>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5"
                strokeLinejoin="round" opacity="0.55" />
    </svg>
  );
}

/* ── 分頁:點擊統計 ─────────────────────────────────────────────────────── */
function StatsTab({ stats }) {
  const [sort, setSort] = useState('views');
  const rows = useMemo(() => {
    const r = [...stats];
    r.sort((a, b) => (sort === 'views'
      ? (b.totalViews || 0) - (a.totalViews || 0)
      : String(a.title || a.id).localeCompare(String(b.title || b.id), 'zh-TW')));
    return r;
  }, [stats, sort]);

  const synced = stats.length
    ? stats.map((s) => s.syncedAt).filter(Boolean).sort().pop() : null;

  if (!stats.length) {
    return (
      <div>
        <div className="eyebrow">Article Analytics</div>
        <h2 className="admin-h2">文章點擊統計</h2>
        <p className="admin-note">
          每篇文章都已埋入 GA4 追蹤碼。數字要進到這個畫面,需要在本機跑一次同步:
          <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}> python3 scripts/sync_ga_stats.py </code>
          —— 它會用 service account 讀 GA4 Data API 再寫進 Firestore,金鑰因此不必放到前端。
        </p>
        <div className="card">
          <div className="empty">尚無統計資料。埋點剛上線,GA4 的非即時報表約需 24–48 小時才穩定。</div>
        </div>
      </div>
    );
  }

  const total = rows.reduce((n, r) => n + (r.totalViews || 0), 0);
  return (
    <div>
      <div className="eyebrow">Article Analytics</div>
      <h2 className="admin-h2">文章點擊統計</h2>
      <p className="admin-note">
        共 {rows.length} 篇 · 累計 {total.toLocaleString()} 次瀏覽。
        {synced && <> 最後同步:{String(synced).slice(0, 16).replace('T', ' ')}。</>}
        {' '}資料由本機 <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>sync_ga_stats.py</code> 更新;
        GA4 非即時報表約有 24–48 小時延遲,數字偏低不代表沒人看。
      </p>
      <div className="row" style={{ marginBottom: 18 }}>
        <button className={'btn small ' + (sort === 'views' ? '' : 'ghost')}
                onClick={() => setSort('views')}>依瀏覽數</button>
        <button className={'btn small ' + (sort === 'title' ? '' : 'ghost')}
                onClick={() => setSort('title')}>依標題</button>
      </div>
      <div className="grid">
        {rows.map((r) => (
          <div className="card" key={r.id}>
            <div className={'bar ' + tone(r.shelf)} />
            <div className="card-title" style={{ display: 'block' }}>{r.title || r.id}</div>
            <div className="stat-row">
              <div>
                <div className="stat-n">{(r.totalViews || 0).toLocaleString()}</div>
                <div className="stat-lab">Views</div>
              </div>
              <div>
                <div className="stat-n">{(r.totalUsers || 0).toLocaleString()}</div>
                <div className="stat-lab">Readers</div>
              </div>
            </div>
            <Spark daily={r.daily} />
            <div className="card-meta" style={{ marginTop: 10 }}>{r.id}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 分頁:通訊錄 ───────────────────────────────────────────────────────── */
const ROSTER_PAGE = 50;

function RosterTab({ segs, events, reasons, subs, onBlockConfirm, reload }) {
  const [segId, setSegId] = useState('mcp');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const [regs, setRegs] = useState({});
  const [expandBusy, setExpandBusy] = useState(null);
  const [expandErr, setExpandErr] = useState({});
  const [adding, setAdding] = useState(false);
  const [confirmSub, setConfirmSub] = useState(null);
  const [visible, setVisible] = useState(ROSTER_PAGE);

  const seg = segs.find((s) => s.id === segId) || segs[0];
  const eventById = useMemo(
    () => Object.fromEntries(events.map((e) => [e.id, e])), [events]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const r = needle
      ? seg.rows.filter((s) => (s.email || '').includes(needle) ||
                               (s.name || '').toLowerCase().includes(needle))
      : seg.rows;
    return [...r].sort((a, b) => String(b.lastSeenAt || '').localeCompare(String(a.lastSeenAt || '')));
  }, [seg, q]);

  // 換分眾或改搜尋字時,已展開的「載入更多」進度要歸零,不然會出現
  // 「顯示 1–50 / 共 12」這種矛盾畫面。
  useEffect(() => { setVisible(ROSTER_PAGE); }, [segId, q]);
  const shown = rows.slice(0, visible);

  const loadRegs = useCallback(async (id) => {
    setExpandBusy(id); setExpandErr((m) => ({ ...m, [id]: '' }));
    try {
      const snap = await window.fbDb.collection('subscribers').doc(id)
        .collection('registrations').get();
      setRegs((m) => ({ ...m, [id]: snap.docs.map((d) => d.data()) }));
    } catch (e) {
      setExpandErr((m) => ({ ...m, [id]: String((e && e.message) || e) }));
    }
    setExpandBusy(null);
  }, []);

  const toggleOpen = useCallback((id) => {
    const willOpen = open !== id;
    setOpen(willOpen ? id : null);
    if (willOpen && !regs[id]) loadRegs(id);
  }, [open, regs, loadRegs]);

  return (
    <div>
      <div className="eyebrow">Contacts</div>
      <h2 className="admin-h2">電子報通訊錄</h2>
      <p className="admin-note">
        一人一筆(以正規化 email 為鍵),底下掛每一次報名紀錄。
        左側分眾全部是「查詢」而非另一份名單 —— 分類是從「這個人報過哪些場次、
        那些場次現在的分類是什麼」即時算出來,在事件管理頁改分類會馬上反映在這裡。
        下半部的「名單軌跡」來自 GWS 的名單檔:那是<b>曾出現在哪一份名單上</b>,
        不是報名紀錄,兩者刻意分開。
      </p>

      <div className="row" style={{ marginBottom: 20 }}>
        <button className="btn" onClick={() => setAdding(!adding)}>
          {adding ? '收起' : '＋ 手動補入聯絡人'}
        </button>
      </div>
      {adding && (
        <AddContact events={events} existing={subs}
                    onCancel={() => setAdding(false)}
                    onDone={async () => { setAdding(false); await reload(); }} />
      )}
      {confirmSub && (
        <BlockConfirmPanel sub={confirmSub} reasons={reasons}
                            onCancel={() => setConfirmSub(null)}
                            onConfirm={onBlockConfirm} />
      )}

      <div className="roster">
        <div className="roster-nav">
          {segs.map((s, i) => (
            <React.Fragment key={s.id}>
              {s.group === 'list' && (i === 0 || segs[i - 1].group !== 'list') && (
                <div className="eyebrow" style={{ marginTop: 18, marginBottom: 6 }}>
                  名單軌跡 · from GWS
                </div>)}
              <button className={'seg ' + (s.id === segId ? 'on' : '')}
                      onClick={() => { setSegId(s.id); setOpen(null); }}>
                <span>{s.name}</span>
                <span className="seg-n">{s.rows.length}</span>
              </button>
            </React.Fragment>
          ))}
        </div>

        <div>
          {/* 手機版用下拉取代整排 .seg 按鈕 —— 不用捲一大串才看到表格。 */}
          <div className="roster-select-wrap">
            <label className="field-label" htmlFor="roster-seg">選擇分眾</label>
            <select id="roster-seg" className="inp" value={segId}
                    onChange={(e) => { setSegId(e.target.value); setOpen(null); }}>
              {segs.map((s) => (
                <option key={s.id} value={s.id}>{s.name}（{s.rows.length}）</option>
              ))}
            </select>
          </div>

          <div className="roster-meta">
            <span className="eyebrow">{seg.name}</span>
            <span className="card-meta">
              {q.trim() ? `符合 ${rows.length} / 分眾共 ${seg.rows.length} 人` : `共 ${seg.rows.length} 人`}
            </span>
          </div>

          <div className="row" style={{ marginBottom: 14 }}>
            <div className="field" style={{ maxWidth: 300 }}>
              <label className="field-label" htmlFor="roster-q">搜尋</label>
              <input id="roster-q" className="inp" placeholder="Email 或姓名…"
                     value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>
          {seg.hint && <div className="admin-note" style={{ marginBottom: 14 }}>ⓘ {seg.hint}</div>}

          {!rows.length ? <div className="card"><div className="empty">此分眾目前沒有人</div></div> : (
            <>
            <div className="card" style={{ padding: '6px 14px 14px' }}>
              <div className="table-scroll">
              <table className="tbl tbl-contacts">
                <thead>
                  <tr>
                    <th>Email</th><th>姓名</th><th>報過的場次</th><th>狀態</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((s) => (
                    <React.Fragment key={s.id}>
                      <tr>
                        <td className="mono">{s.email}</td>
                        <td>{s.name || <span style={{ color: 'var(--ink-faint)' }}>—</span>}</td>
                        <td>
                          {effectiveCats(s, eventById).map((c) => (
                            <span key={c} className={'chip ' + tone(c)}>{catLabel(c)}</span>
                          ))}
                          {!!(s.eventIds || []).length &&
                            <span className="card-meta"> {s.eventIds.length} 場</span>}
                          {!(s.eventIds || []).length &&
                            <span className="card-meta">僅名單,無報名紀錄</span>}
                          {!!(s.lists || []).length && (
                            <div style={{ marginTop: 4 }}>
                              {s.lists.map((l) => (
                                <span key={l} className="chip" style={{ fontSize: 12 }}>{l}</span>
                              ))}
                            </div>)}
                        </td>
                        <td>
                          {s.blocked
                            ? (s.blockReasons || []).map((r) => (
                                <span key={r} className="chip block">
                                  {(reasons.find((x) => x.id === r) || {}).label || r}
                                </span>))
                            : (s.testAddress
                                ? <span className="chip">測試位址</span>
                                : <span className="card-meta">可寄送</span>)}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button className="btn small ghost" onClick={() => toggleOpen(s.id)}
                                  disabled={expandBusy === s.id}
                                  aria-expanded={open === s.id}>
                            {open === s.id ? '收合' : '明細'}
                          </button>{' '}
                          <button className="btn small ghost" onClick={() => setConfirmSub(s)}>
                            {s.blocked ? '解封' : '封鎖'}
                          </button>
                        </td>
                      </tr>
                      {open === s.id && (
                        <tr>
                          <td colSpan={5} style={{ background: 'var(--paper-soft)' }}>
                            {!regs[s.id] ? (
                              expandBusy === s.id
                                ? <span className="card-meta" role="status" aria-live="polite">載入中…</span>
                                : expandErr[s.id]
                                  ? (
                                    <span className="err" role="alert" style={{ display: 'inline-block' }}>
                                      {expandErr[s.id]}{' '}
                                      <button className="btn small ghost" onClick={() => loadRegs(s.id)}>重試</button>
                                    </span>)
                                  : null
                            ) : (
                              regs[s.id].length ? (
                              <div>
                                {regs[s.id]
                                  .sort((a, b) => String(a.eventDate).localeCompare(String(b.eventDate)))
                                  .map((r, i) => (
                                  <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                                    <span className={'chip ' + tone(r.category)}>
                                      {(eventById[r.eventId] || {}).name || r.eventId}
                                    </span>
                                    <span className="card-meta"> {r.eventDate} </span>
                                    {(r.tickets || []).map((t) => (
                                      <span key={t} className="chip">{t}</span>))}
                                    {!!(r.ticketsRaw || []).length && (
                                      <div style={{ fontSize: 12, color: 'var(--ink-mute)', marginTop: 4 }}>
                                        原文:{r.ticketsRaw.join('｜')}
                                      </div>)}
                                  </div>
                                ))}
                              </div>
                              ) : <div className="card-meta">此人只在名單上,沒有報名紀錄</div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
              </div>
            </div>
            <div className="row" style={{ marginTop: 14, justifyContent: 'space-between' }}>
              <span className="roster-range">顯示 1–{shown.length} / 共 {rows.length}</span>
              {visible < rows.length && (
                <button className="btn small ghost" onClick={() => setVisible((v) => v + ROSTER_PAGE)}>
                  載入更多（還有 {rows.length - visible}）
                </button>
              )}
            </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── 匯出:集合運算 ─────────────────────────────────────────────────────────
   匯出頁不再是「單選一個分眾」,而是一個 ＋／－ 運算籃:任意數量的場次、分眾、
   名單軌跡、手動貼上的清單都可以相加或相減,系統負責去重,最後恆定扣掉封鎖者
   與測試位址。

   為什麼要自己做去重:實務上寄信是「8 月場 ＋ 9 月場 ＋ 永久收件人,扣掉上週
   已經寄過的那場」。過去只能匯出多份 CSV 再到 Excel 手工去重 —— 而手工去重
   正是漏寄/重複寄的來源。

   所有運算都在前端記憶體完成(App 已一次載入 events/subscribers),不需要任何
   額外的 Firestore 讀取。特別注意:registrations 子集合在 firestore.rules 是
   巢狀 match,不授予 collectionGroup 權限,前端跨訂閱者查詢會被拒 —— 因此場次
   成員一律走 subscribers.eventIds,不查 registrations。 */
const EXPORT_PAGE = 50;

/* 一段貼上的文字 → 正規化後的 email 陣列。
   切法刻意寬鬆(逗號/分號/空白/換行/全形標點都算分隔),因為使用者會從郵件
   軟體、Excel、聊天訊息各種地方貼過來。正規化一律走 normalizeEmail —— 那支
   與 import_roster.py 的 doc id 規則同源,自己另寫一份必然漂移。 */
function parsePastedEmails(text) {
  const out = [];
  const seen = new Set();
  String(text || '').split(/[\s,;、，；｜|]+/).forEach((tok) => {
    const e = normalizeEmail(tok);
    if (e && !seen.has(e)) { seen.add(e); out.push(e); }
  });
  return out;
}

/* 集合運算本體 —— 刻意寫成 component 外的純函式:
   1. 流水帳 UI 需要「每一階段被拿掉的是誰」,不能只回一個最終陣列;
   2. 純函式才驗得起來(可在 console 餵合成資料驗去重/差集/封鎖扣除)。

   key 的定義:通訊錄裡的人用 subscriber doc id(= 正規化 email);貼上但通訊錄
   查無此人的位址,用位址本身當 key —— 兩者天生不會相撞,因為前者就在 subs 裡。 */
function computeBasket({ subs, sources, manualExcluded, keepBlocked, includeUnknown }) {
  const byKey = new Map();
  subs.forEach((s) => byKey.set(s.id, s));

  const memberKeys = (src) => (includeUnknown
    ? [...src.ids, ...src.unknownEmails]
    : [...src.ids]);

  // 2. 相加(未去重)—— 使用者說的「最後相加」就是這個機械加總,
  //    它與去重後的數字之差,正是「重複了幾筆」。
  const sourcesByKey = new Map();
  let rawSum = 0;
  const plusUnion = new Set();
  sources.filter((s) => s.sign === 1).forEach((src) => {
    const ks = memberKeys(src);
    rawSum += ks.length;
    ks.forEach((k) => {
      plusUnion.add(k);
      const arr = sourcesByKey.get(k);
      if (arr) arr.push(src.name); else sourcesByKey.set(k, [src.name]);
    });
  });
  const dupCount = rawSum - plusUnion.size;
  const dupKeys = [...plusUnion].filter((k) => (sourcesByKey.get(k) || []).length >= 2);

  // 4. 減去 － 項
  const minusUnion = new Set();
  sources.filter((s) => s.sign === -1).forEach(
    (src) => memberKeys(src).forEach((k) => minusUnion.add(k)));
  const removedByMinus = [...plusUnion].filter((k) => minusUnion.has(k));
  const afterMinus = new Set([...plusUnion].filter((k) => !minusUnion.has(k)));

  // 5. 結果清單上逐人勾除
  const removedByManual = [...afterMinus].filter((k) => manualExcluded.has(k));
  const afterManual = new Set([...afterMinus].filter((k) => !manualExcluded.has(k)));

  // 6. 封鎖 / 測試位址 —— 除非明確勾了「僅供檢視」,否則永遠扣掉。
  const isBlocked = (k) => {
    const s = byKey.get(k);
    return !!(s && (s.blocked || s.testAddress));
  };
  const removedByBlock = keepBlocked ? [] : [...afterManual].filter(isBlocked);
  const final = keepBlocked
    ? afterManual : new Set([...afterManual].filter((k) => !isBlocked(k)));

  return { rawSum, plusUnion, dupCount, dupKeys, afterMinus, afterManual, final,
           removedByMinus, removedByManual, removedByBlock, sourcesByKey, byKey };
}

function ExportTab({ segs, events, subs, basket, setBasket }) {
  const { terms, excluded, keepBlocked, includeUnknown, pastes } = basket;
  const [q, setQ] = useState('');
  const [view, setView] = useState('final');
  const [sep, setSep] = useState(', ');
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(EXPORT_PAGE);
  // 一組都不預設收合:名單軌跡被收起來時,使用者會以為那些名單根本不存在。
  // 清單長度由搜尋框 + .src-list 的可捲高度處理,不靠藏東西。
  const [collapsed, setCollapsed] = useState(() => new Set());

  const eventById = useMemo(
    () => Object.fromEntries(events.map((e) => [e.id, e])), [events]);
  const subById = useMemo(() => {
    const m = new Map(); subs.forEach((s) => m.set(s.id, s)); return m;
  }, [subs]);

  /* ── 來源目錄 ──────────────────────────────────────────────────────────
     場次成員與 EventsTab.regCount 同一個判準(subscribers.eventIds),分眾直接
     沿用 buildSegments 的產物 —— 分眾定義只有一份,這裡不重新發明。 */
  const catalog = useMemo(() => {
    const evs = [...events]
      .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
      .map((e) => ({
        kind: 'event', key: e.id, name: e.name || e.id, meta: e.date || '',
        cat: e.category,
        ids: new Set(subs.filter((s) => (s.eventIds || []).includes(e.id)).map((s) => s.id)),
        unknownEmails: [],
      }));
    const mk = (s) => ({
      kind: 'seg', key: s.id, name: s.name, meta: '', cat: null,
      ids: new Set(s.rows.map((r) => r.id)), unknownEmails: [],
    });
    const segMain = segs.filter((s) => s.group !== 'list').map(mk);
    const segList = segs.filter((s) => s.group === 'list').map(mk);
    const pas = pastes.map((p) => {
      const ids = new Set(); const unknown = [];
      parsePastedEmails(p.text).forEach(
        (e) => (subById.has(e) ? ids.add(e) : unknown.push(e)));
      return { kind: 'paste', key: p.key, name: p.label.trim() || '貼上清單',
               meta: '', cat: null, ids, unknownEmails: unknown, text: p.text,
               label: p.label };
    });
    return { evs, segMain, segList, pas, all: [...evs, ...segMain, ...segList, ...pas] };
  }, [events, subs, segs, pastes, subById]);

  const srcOf = useCallback(
    (kind, key) => catalog.all.find((s) => s.kind === kind && s.key === key),
    [catalog]);

  const signOf = useCallback((kind, key) => {
    const t = terms.find((x) => x.kind === kind && x.key === key);
    return t ? t.sign : 0;
  }, [terms]);

  /* ── 籃子操作 ─────────────────────────────────────────────────────────
     同一個 (kind,key) 在籃子裡只能有一項:已是 ＋ 再按 － 是翻號,不是新增。 */
  const setSign = (kind, key, sign) => setBasket((b) => {
    const rest = b.terms.filter((t) => !(t.kind === kind && t.key === key));
    const cur = b.terms.find((t) => t.kind === kind && t.key === key);
    return { ...b, terms: (cur && cur.sign === sign) ? rest : [...rest, { kind, key, sign }] };
  });
  // 點名字本體 = 「只選這個」。保住改版前的一鍵單選行為,肌肉記憶不會壞。
  const only = (kind, key) => setBasket(
    (b) => ({ ...b, terms: [{ kind, key, sign: 1 }], excluded: [] }));
  const clearAll = () => setBasket(
    (b) => ({ ...b, terms: [], excluded: [] }));

  const addPaste = () => {
    const key = 'p' + Date.now().toString(36);
    setBasket((b) => ({ ...b,
      pastes: [...b.pastes, { key, label: '', text: '' }],
      terms: [...b.terms, { kind: 'paste', key, sign: 1 }] }));
  };
  const patchPaste = (key, patch) => setBasket((b) => ({ ...b,
    pastes: b.pastes.map((p) => (p.key === key ? { ...p, ...patch } : p)) }));
  const dropPaste = (key) => setBasket((b) => ({ ...b,
    pastes: b.pastes.filter((p) => p.key !== key),
    terms: b.terms.filter((t) => !(t.kind === 'paste' && t.key === key)) }));

  const toggleExcluded = (k) => setBasket((b) => ({ ...b,
    excluded: b.excluded.includes(k)
      ? b.excluded.filter((x) => x !== k) : [...b.excluded, k] }));

  /* ── 運算 ─────────────────────────────────────────────────────────────── */
  const selected = useMemo(() => terms
    .map((t) => { const s = srcOf(t.kind, t.key); return s ? { ...s, sign: t.sign } : null; })
    .filter(Boolean), [terms, srcOf]);

  const res = useMemo(() => computeBasket({
    subs, sources: selected, manualExcluded: new Set(excluded),
    keepBlocked, includeUnknown,
  }), [subs, selected, excluded, keepBlocked, includeUnknown]);

  // 還原成列時一律照 subs 既有順序,不用 Set 的迭代序 —— 後者會隨操作順序
  // 跳動,使用者會以為名單本身變了。貼上但通訊錄查無的位址併在最後。
  const orderRows = useCallback((keys) => {
    const set = keys instanceof Set ? keys : new Set(keys);
    const out = [];
    subs.forEach((s) => { if (set.has(s.id)) out.push(s); });
    set.forEach((k) => {
      if (!subById.has(k)) out.push({ id: k, email: k, name: '', _pasteOnly: true });
    });
    return out;
  }, [subs, subById]);

  const unknownTotal = useMemo(() => {
    const u = new Set();
    catalog.pas.forEach((p) => p.unknownEmails.forEach((e) => u.add(e)));
    return u.size;
  }, [catalog]);

  const VIEWS = [
    { id: 'sum',    lab: '相加(未去重)', n: res.rawSum,               keys: res.plusUnion,
      note: '各加項的人數機械加總。同一個人報了兩場就算兩次。' },
    { id: 'dup',    lab: '重複',         n: res.dupKeys.length,        keys: res.dupKeys,
      note: '同時出現在 2 個以上加項的人。去重時每人只留一筆,共扣掉 ' + res.dupCount + ' 筆。' },
    { id: 'minus',  lab: '被減項扣掉',   n: res.removedByMinus.length, keys: res.removedByMinus,
      note: '被 － 項扣掉的人。' },
    { id: 'manual', lab: '手動勾除',     n: res.removedByManual.length, keys: res.removedByManual,
      note: '在結果清單上逐人勾除的人。取消勾選即可放回。' },
    { id: 'block',  lab: '封鎖/測試',    n: res.removedByBlock.length, keys: res.removedByBlock,
      note: '被封鎖者與測試位址,一律扣除。' },
    { id: 'final',  lab: '最終名單',     n: res.final.size,            keys: res.final,
      note: '這就是要寄出去的名單。' },
  ];
  const curView = VIEWS.find((v) => v.id === view) || VIEWS[5];
  const rows = useMemo(() => orderRows(curView.keys), [orderRows, curView]);

  useEffect(() => { setVisible(EXPORT_PAGE); }, [view, terms, excluded, keepBlocked]);
  const shown = rows.slice(0, visible);

  /* ── 匯出 ─────────────────────────────────────────────────────────────── */
  const slug = () => {
    const s = terms.map((t) => (t.sign === 1 ? '+' : '-') +
      (t.kind === 'paste' ? 'paste' : t.key)).join('')
      .replace(/[^\w+\-.一-鿿]/g, '_').replace(/^\+/, '');
    return ((view === 'final' ? '' : view + '_') + (s || 'export')).slice(0, 80);
  };

  const go = () => downloadCsv(
    `goodedunote_${slug()}_${new Date().toISOString().slice(0, 10)}.csv`,
    // 既有 9 欄原樣保留(欄序不動,舊的下游用法不會壞),尾端加兩欄來源標註。
    [['email', 'name', 'categories', 'events', 'lists', 'firstSeenAt', 'lastSeenAt',
      'blocked', 'blockReasons', 'sources', 'sourceCount'],
     ...rows.map((s) => {
       const src = res.sourcesByKey.get(s.id) || [];
       return [s.email, s.name || '', effectiveCats(s, eventById).join(' '),
               (s.eventIds || []).join(' '), (s.lists || []).join('｜'),
               s.firstSeenAt || '', s.lastSeenAt || '',
               s.blocked ? 'Y' : '', (s.blockReasons || []).join(' '),
               src.join('｜'), String(src.length)];
     })]);

  const emailText = rows.map((s) => s.email).join(sep);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(emailText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      // clipboard API 在部分情境會被擋(權限、非使用者手勢)。
      // 退而求其次:把文字選起來,使用者按 Cmd/Ctrl+C 即可。
      const el = document.getElementById('email-only-box');
      if (el) { el.focus(); el.select(); }
    }
  };

  /* ── 來源列 ───────────────────────────────────────────────────────────── */
  const needle = q.trim().toLowerCase();
  const match = (s) => !needle || (s.name || '').toLowerCase().includes(needle) ||
    (s.key || '').toLowerCase().includes(needle) || (s.meta || '').includes(needle);

  const toggleGroup = (g) => setCollapsed((c) => {
    const n = new Set(c); if (n.has(g)) n.delete(g); else n.add(g); return n;
  });

  // 刻意寫成「回傳元素的函式」而不是 inline component:在 render 裡定義的
  // component 每次都是新的型別,React 會整棵子樹 remount(輸入框失焦、捲動位置
  // 重置)。函式呼叫則只是產生元素,沒有這個問題。
  const srcRow = (s) => {
    const sign = signOf(s.kind, s.key);
    const n = s.ids.size + (includeUnknown ? s.unknownEmails.length : 0);
    return (
      <div className="term-row" key={s.kind + ':' + s.key}>
        <button className={'seg' + (sign === 1 ? ' plus' : sign === -1 ? ' minus' : '')}
                onClick={() => only(s.kind, s.key)}
                title="只選這個(清空籃子)">
          <span className="term-name">
            {s.name}
            {s.meta && <span className="term-meta">{s.meta}</span>}
            {s.cat && <span className={'chip ' + tone(s.cat)}>{catLabel(s.cat)}</span>}
          </span>
          <span className="seg-n">{n}</span>
        </button>
        {/* ＋／－ 不能只靠顏色分辨(色盲安全),符號本身必須看得見。 */}
        <button className={'pm-btn' + (sign === 1 ? ' on-plus' : '')}
                aria-pressed={sign === 1} aria-label={'把「' + s.name + '」加入加項'}
                onClick={() => setSign(s.kind, s.key, 1)}>＋</button>
        <button className={'pm-btn' + (sign === -1 ? ' on-minus' : '')}
                aria-pressed={sign === -1} aria-label={'把「' + s.name + '」設為減項'}
                onClick={() => setSign(s.kind, s.key, -1)}>－</button>
      </div>
    );
  };

  const group = (id, title, items, hint) => {
    const shut = collapsed.has(id);
    const list = items.filter(match);
    if (!list.length && needle) return null;
    return (
      <div className="src-group" key={id}>
        <button className="src-head" aria-expanded={!shut} onClick={() => toggleGroup(id)}>
          <span className="eyebrow" style={{ marginBottom: 0 }}>{title}</span>
          <span className="seg-n">{shut ? '▸' : '▾'} {list.length}</span>
        </button>
        {hint && !shut && <div className="card-meta" style={{ marginBottom: 8 }}>{hint}</div>}
        {!shut && list.map(srcRow)}
      </div>
    );
  };

  const chipFor = (t) => {
    const s = srcOf(t.kind, t.key);
    return (
      <button key={t.kind + ':' + t.key}
              className={'chip ' + (t.sign === 1 ? 'plus' : 'minus')}
              onClick={() => setSign(t.kind, t.key, t.sign)}
              aria-label={'移除' + (t.sign === 1 ? '加項' : '減項') + '「' + (s ? s.name : t.key) + '」'}>
        {(t.sign === 1 ? '＋ ' : '－ ') + (s ? s.name : t.key)} ×
      </button>
    );
  };

  const plusTerms = terms.filter((t) => t.sign === 1);
  const minusTerms = terms.filter((t) => t.sign === -1);
  const blockedInPlus = plusTerms.some(
    (t) => t.kind === 'seg' && t.key === 'blocked');

  return (
    <div>
      <div className="eyebrow">Export</div>
      <h2 className="admin-h2">匯出名單</h2>
      <p className="admin-note">
        用 <b>＋</b> 把多個場次/分眾/名單加起來,用 <b>－</b> 扣掉不想寄的那些,
        系統自動去重。除非勾了「僅供檢視」,否則<b>封鎖者與測試位址一律扣除</b>。
        點來源的名字 = 只選這個(清空籃子)。CSV 帶 UTF-8 BOM,Excel 直接開不會亂碼。
      </p>

      <div className="export-grid">
        {/* ── 左軌:來源 ─────────────────────────────────────────────── */}
        <div className="card">
          <div className="card-title">
            來源<span className="card-meta">{catalog.all.length} 項可選</span>
          </div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label className="field-label" htmlFor="src-q">搜尋場次 / 分眾</label>
            <input id="src-q" className="inp" placeholder="場次名稱、代碼或日期"
                   value={q} onChange={(e) => setQ(e.target.value)} />
          </div>

          <div className="src-list">
            {group('event', '場次', catalog.evs, '依日期新到舊。人數 = 報過這一場的人。')}
            {group('seg', '分眾', catalog.segMain)}
            {group('list', '名單軌跡 · from GWS', catalog.segList,
                   '曾出現在哪一份名單上,不是報名紀錄。')}
            <div className="src-group">
              <div className="src-head" style={{ cursor: 'default' }}>
                <span className="eyebrow" style={{ marginBottom: 0 }}>手動貼上 email</span>
                <span className="seg-n">{catalog.pas.length}</span>
              </div>
              {catalog.pas.map((p) => (
                <div key={p.key} className="paste-box">
                  {srcRow(p)}
                  <input className="inp" style={{ fontSize: 12, marginBottom: 6 }}
                         aria-label="這份貼上清單的名稱"
                         placeholder="給這份清單一個名字(選填)"
                         value={p.label} onChange={(e) => patchPaste(p.key, { label: e.target.value })} />
                  <textarea className="inp mono-box" rows={4}
                            aria-label={p.name + ' 的 email 內容'}
                            placeholder="貼上 email,逗號/分號/換行分隔都可以"
                            value={p.text} onChange={(e) => patchPaste(p.key, { text: e.target.value })} />
                  <div className="row" style={{ marginTop: 6 }}>
                    <span className="card-meta">
                      通訊錄內 {p.ids.size} · 不在通訊錄 {p.unknownEmails.length}
                    </span>
                    <button className="btn small ghost" onClick={() => dropPaste(p.key)}>刪除</button>
                  </div>
                </div>
              ))}
              <button className="btn small ghost" onClick={addPaste}>＋ 新增貼上清單</button>
            </div>
          </div>
        </div>

        {/* ── 右軌 ───────────────────────────────────────────────────── */}
        <div className="export-col">
          <div className="card">
            <div className="card-title">
              運算籃
              <span className="card-meta">{terms.length} 項</span>
            </div>
            {!terms.length ? (
              <div className="empty">左邊按 ＋ 挑第一個來源</div>
            ) : (
              <>
                <div className="field-label">加項（聯集後去重）</div>
                <div className="chip-row">
                  {plusTerms.length ? plusTerms.map(chipFor)
                    : <span className="card-meta">尚未選任何加項 → 結果為空</span>}
                </div>
                {!!minusTerms.length && (
                  <>
                    <div className="field-label" style={{ marginTop: 12 }}>減項（從加項中扣掉）</div>
                    <div className="chip-row">{minusTerms.map(chipFor)}</div>
                  </>
                )}
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn small ghost" onClick={clearAll}>清空籃子</button>
                </div>
              </>
            )}

            <div className="opt-row">
              <label className="opt">
                <input type="checkbox" checked={keepBlocked}
                       onChange={(e) => setBasket((b) => ({ ...b, keepBlocked: e.target.checked }))} />
                <span>不扣除封鎖／測試（僅供檢視，<b>不要拿去寄信</b>）</span>
              </label>
              {unknownTotal > 0 && (
                <label className="opt">
                  <input type="checkbox" checked={includeUnknown}
                         onChange={(e) => setBasket((b) => ({ ...b, includeUnknown: e.target.checked }))} />
                  <span>一併納入貼上清單中不在通訊錄的 {unknownTotal} 個位址</span>
                </label>
              )}
            </div>
          </div>

          {/* ── 運算流水帳 ──────────────────────────────────────────────
              每一格都點得開 —— 去重掉的是誰、被減掉的是誰要看得見,
              不能只給一個數字然後默默處理掉。 */}
          <div className="card">
            <div className="card-title">運算流水帳</div>
            <div className="pipeline" role="tablist" aria-label="運算階段">
              {VIEWS.map((v, i) => (
                <React.Fragment key={v.id}>
                  {i > 0 && <span className="pipe-arrow" aria-hidden="true">→</span>}
                  <button role="tab" aria-selected={view === v.id}
                          className={'pipe-step' + (view === v.id ? ' on' : '') +
                                     (v.id === 'final' ? ' final' : '')}
                          onClick={() => setView(v.id)}>
                    <span className="stat-n" aria-live="polite">
                      {(v.id === 'sum' || v.id === 'final' ? '' : '−') + v.n}
                    </span>
                    <span className="stat-lab">{v.lab}</span>
                  </button>
                </React.Fragment>
              ))}
            </div>
            <p className="admin-note" style={{ marginTop: 12, marginBottom: 0 }}>
              {curView.note}
            </p>
            {blockedInPlus && !keepBlocked && (
              <div className="err" role="status" style={{ marginTop: 10 }}>
                加項裡有「封鎖區」,但封鎖者在最後一步會被扣光。
                要檢視他們請勾上方的「不扣除封鎖／測試」。
              </div>
            )}
          </div>

          {/* ── 結果清單 ────────────────────────────────────────────── */}
          <div className="card" style={{ padding: '6px 14px 14px' }}>
            <div className="card-title" style={{ marginTop: 14 }}>
              {curView.lab}
              <span className="card-meta">{rows.length} 人</span>
            </div>
            {view !== 'final' && (
              <div className="view-warn" role="status">
                目前檢視與匯出的是〈{curView.lab}〉,<b>不是最終名單</b>。
                <button className="btn small" style={{ marginLeft: 10 }}
                        onClick={() => setView('final')}>回到最終名單（{res.final.size}）</button>
              </div>
            )}
            {!rows.length ? <div className="empty">這一階段沒有任何人</div> : (
              <>
                <div className="table-scroll">
                  <table className="tbl">
                    <thead><tr>
                      <th style={{ width: 34 }}>勾除</th>
                      <th>Email</th><th>姓名</th><th>來源</th><th>狀態</th>
                    </tr></thead>
                    <tbody>
                      {shown.map((s) => {
                        const src = res.sourcesByKey.get(s.id) || [];
                        return (
                          <tr key={s.id}>
                            <td>
                              <input type="checkbox" checked={excluded.includes(s.id)}
                                     aria-label={'排除 ' + s.email}
                                     onChange={() => toggleExcluded(s.id)} />
                            </td>
                            <td className="mono">{s.email}</td>
                            <td>{s.name || '—'}</td>
                            <td>
                              {src.length
                                ? src.map((n, i) => <span key={i} className="chip">{n}</span>)
                                : <span className="card-meta">—</span>}
                            </td>
                            <td>
                              {s.blocked && <span className="chip block">封鎖</span>}
                              {s.testAddress && <span className="chip block">測試</span>}
                              {s._pasteOnly && <span className="chip">不在通訊錄</span>}
                              {src.length >= 2 && <span className="chip">重複 {src.length}</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="row" style={{ marginTop: 14, justifyContent: 'space-between' }}>
                  <span className="roster-range">顯示 1–{shown.length} / 共 {rows.length}</span>
                  {visible < rows.length && (
                    <button className="btn small ghost" onClick={() => setVisible((v) => v + EXPORT_PAGE)}>
                      載入更多（還有 {rows.length - visible}）
                    </button>
                  )}
                </div>
              </>
            )}
          </div>

          {/* ── Email Only ─────────────────────────────────────────── */}
          <div className="card">
            <div className="card-title">
              Email Only
              <span className="card-meta">{curView.lab} · {rows.length} 個位址</span>
            </div>
            <p className="admin-note" style={{ marginBottom: 14 }}>
              全選複製後直接貼進郵件的收件人欄。收件人請貼在<b>密件副本(BCC)</b>,
              否則所有人會看見彼此的 email。
            </p>
            <div className="row" style={{ marginBottom: 12 }}>
              {[[', ', '逗號'], ['; ', '分號'], ['\n', '換行']].map(([v, label]) => (
                <button key={label} className={'btn small ' + (sep === v ? '' : 'ghost')}
                        onClick={() => setSep(v)}>{label}分隔</button>
              ))}
            </div>
            <label className="field-label" htmlFor="email-only-box">匯出的 Email 清單（唯讀）</label>
            <textarea id="email-only-box" className="inp mono-box" readOnly
                      value={emailText} rows={12}
                      onFocus={(e) => e.target.select()} />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={copy} disabled={!rows.length}
                      aria-live="polite">{copied ? '已複製 ✓' : '複製全部'}</button>
              <button className="btn ghost" onClick={go} disabled={!rows.length}>下載 CSV</button>
              <span className="card-meta" role="status" aria-live="polite">
                {copied ? '已複製到剪貼簿' : `${emailText.length.toLocaleString()} 字元`}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── 分頁:事件管理 ─────────────────────────────────────────────────────── */
function EventsTab({ events, subs, reload }) {
  const [f, setF] = useState({ id: '', name: '', category: 'mcp', date: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [savingCat, setSavingCat] = useState(null);
  const [catErr, setCatErr] = useState({});

  const save = async () => {
    if (!f.id.trim() || !f.name.trim()) { setErr('事件代碼與名稱為必填'); return; }
    setBusy(true); setErr('');
    try {
      await window.fbDb.collection('events').doc(f.id.trim()).set(
        { name: f.name.trim(), category: f.category.trim(), date: f.date.trim() }, { merge: true });
      setF({ id: '', name: '', category: 'mcp', date: '' });
      await reload();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };

  const setCat = async (id, category) => {
    setSavingCat(id); setCatErr((m) => ({ ...m, [id]: '' }));
    try {
      await window.fbDb.collection('events').doc(id).set({ category }, { merge: true });
      await reload();
    } catch (e) {
      setCatErr((m) => ({ ...m, [id]: String((e && e.message) || e) }));
    }
    setSavingCat(null);
  };

  const regCount = (id) => subs.filter((s) => (s.eventIds || []).includes(id)).length;

  return (
    <div>
      <div className="eyebrow">Events</div>
      <h2 className="admin-h2">報名種類 / 事件管理</h2>
      <p className="admin-note">
        每一個「報名種類」就是這裡的一筆事件。要開新課程種類:新增一筆、給它一個分類代碼,
        通訊錄與匯出頁就會自動多出對應分眾 —— 不需要改任何程式。
        改既有事件的分類是<b>即時反映</b>在分眾上(通訊錄/匯出每次都直接從這裡的分類算,
        不是另外存一份),不需要重新匯入。
      </p>

      <div className="card" style={{ maxWidth: 620, marginBottom: 26 }}>
        <div className="card-title">新增事件</div>
        <div className="row" style={{ marginBottom: 10, alignItems: 'flex-start' }}>
          <div className="field" style={{ maxWidth: 220 }}>
            <label className="field-label" htmlFor="ev-id">事件代碼</label>
            <input id="ev-id" className="inp" placeholder="如 mcp-2026-09"
                   value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} />
          </div>
          <div className="field" style={{ maxWidth: 130 }}>
            <label className="field-label" htmlFor="ev-date">日期</label>
            <input id="ev-date" className="inp" placeholder="2026-09-20"
                   value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
          </div>
        </div>
        <div className="row" style={{ marginBottom: 14, alignItems: 'flex-start' }}>
          <div className="field" style={{ maxWidth: 220 }}>
            <label className="field-label" htmlFor="ev-name">顯示名稱</label>
            <input id="ev-name" className="inp" placeholder="給人看的活動名稱"
                   value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
          <div className="field" style={{ maxWidth: 130 }}>
            <label className="field-label" htmlFor="ev-cat">分類代碼</label>
            <input id="ev-cat" className="inp" placeholder="mcp / slides / …"
                   value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} />
          </div>
        </div>
        <button className="btn" onClick={save} disabled={busy} aria-live="polite">
          {busy ? '儲存中…' : '新增'}
        </button>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {!events.length ? (
        <div className="card"><div className="empty">目前沒有任何事件,先在上面新增一筆</div></div>
      ) : (
      <div className="card" style={{ padding: '6px 14px 14px' }}>
        <div className="table-scroll">
        <table className="tbl">
          <thead><tr><th>事件代碼</th><th>名稱</th><th>日期</th><th>分類</th><th className="num">匯入筆數</th></tr></thead>
          <tbody>
            {[...events].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
              .map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.id}</td>
                <td>{e.name}</td>
                <td className="mono">{e.date || '—'}</td>
                <td>
                  {/* 欄位標題〈分類〉已提供視覺脈絡,每一列不必再重複印一次可見
                      label(17 列會很吵);無障礙語意改用 aria-label 保留。 */}
                  <input id={'ev-cat-' + e.id} className="inp" style={{ maxWidth: 130, fontSize: 12 }}
                         aria-label={(e.name || e.id) + ' 的分類代碼'}
                         defaultValue={e.category} disabled={savingCat === e.id}
                         onBlur={(ev) => ev.target.value !== e.category && setCat(e.id, ev.target.value.trim())} />
                  <div className="card-meta" style={{ marginTop: 4 }}>
                    改分類即時變更分眾歸屬 · 目前 {regCount(e.id)} 人報名此場
                  </div>
                  {catErr[e.id] && <div className="err" role="alert" style={{ marginTop: 4, padding: '4px 8px' }}>{catErr[e.id]}</div>}
                </td>
                <td className="num">{e.importedCount != null ? e.importedCount : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
      )}
    </div>
  );
}

/* ── 分頁:封鎖區 ───────────────────────────────────────────────────────── */
function BlockTab({ subs, reasons, reload, onBlockConfirm }) {
  const blocked = subs.filter((s) => s.blocked);
  const [nr, setNr] = useState({ id: '', label: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [confirmSub, setConfirmSub] = useState(null);

  const addReason = async () => {
    if (!nr.id.trim() || !nr.label.trim()) { setErr('代碼與標籤為必填'); return; }
    setBusy(true); setErr('');
    try {
      await window.fbDb.collection('blockReasons').doc(nr.id.trim())
        .set({ label: nr.label.trim(), builtin: false }, { merge: true });
      setNr({ id: '', label: '' });
      await reload();
    } catch (e) { setErr(String((e && e.message) || e)); }
    setBusy(false);
  };

  const byReason = {};
  blocked.forEach((s) => (s.blockReasons || []).forEach((r) => {
    byReason[r] = (byReason[r] || 0) + 1;
  }));

  return (
    <div>
      <div className="eyebrow">Suppression</div>
      <h2 className="admin-h2">封鎖區</h2>
      <p className="admin-note">
        目前 {blocked.length} 人被封鎖,匯出時一律自動扣除。一個人可以同時貼多個理由。
        三份來源清單的語義刻意不互換:EMAIL 錯誤是「位址本身壞掉」、退信是「寄了被彈回」、
        退訂是「當事人撤回同意」—— 後者永不移除。
      </p>

      <div className="card" style={{ maxWidth: 620, marginBottom: 26 }}>
        <div className="card-title">封鎖理由標籤<span className="card-meta">{reasons.length} 種</span></div>
        <div style={{ marginBottom: 16 }}>
          {reasons.map((r) => (
            <span key={r.id} className="chip block">
              {r.label} <span style={{ opacity: .6 }}>{byReason[r.id] || 0}</span>
            </span>
          ))}
        </div>
        <div className="row" style={{ alignItems: 'flex-start' }}>
          <div className="field" style={{ maxWidth: 170 }}>
            <label className="field-label" htmlFor="br-id">代碼</label>
            <input id="br-id" className="inp" placeholder="如 spam-trap"
                   value={nr.id} onChange={(e) => setNr({ ...nr, id: e.target.value })} />
          </div>
          <div className="field" style={{ maxWidth: 170 }}>
            <label className="field-label" htmlFor="br-label">顯示標籤</label>
            <input id="br-label" className="inp" placeholder="給人看的名稱"
                   value={nr.label} onChange={(e) => setNr({ ...nr, label: e.target.value })} />
          </div>
          <button className="btn small" onClick={addReason} disabled={busy} aria-live="polite"
                  style={{ alignSelf: 'flex-end' }}>
            {busy ? '新增中…' : '新增理由'}
          </button>
        </div>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {confirmSub && (
        <BlockConfirmPanel sub={confirmSub} reasons={reasons}
                            onCancel={() => setConfirmSub(null)}
                            onConfirm={onBlockConfirm} />
      )}

      {!blocked.length ? <div className="card"><div className="empty">目前沒有被封鎖的聯絡人</div></div> : (
        <div className="card" style={{ padding: '6px 14px 14px' }}>
          <div className="table-scroll">
          <table className="tbl">
            <thead><tr><th>Email</th><th>姓名</th><th>理由</th><th>備註</th><th></th></tr></thead>
            <tbody>
              {blocked.map((s) => (
                <tr key={s.id}>
                  <td className="mono">{s.email}</td>
                  <td>{s.name || '—'}</td>
                  <td>{(s.blockReasons || []).map((r) => (
                    <span key={r} className="chip block">
                      {(reasons.find((x) => x.id === r) || {}).label || r}
                    </span>))}</td>
                  <td style={{ fontSize: 12, color: 'var(--ink-mute)', maxWidth: 300 }}>
                    {(s.blockNote || '').split('\n').slice(0, 2).join(' / ') || '—'}
                  </td>
                  <td><button className="btn small ghost" onClick={() => setConfirmSub(s)}>解封</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 主應用 ─────────────────────────────────────────────────────────────── */
function App() {
  const [user, setUser] = useState(undefined);   // undefined = 還在判斷
  const [denied, setDenied] = useState('');
  const [tab, setTab] = useState('roster');
  const [events, setEvents] = useState([]);
  const [subs, setSubs] = useState([]);
  const [reasons, setReasons] = useState([]);
  const [stats, setStats] = useState([]);
  // 匯出頁的運算籃提到這裡,而不是留在 ExportTab 裡 —— 切分頁時 ExportTab 會
  // unmount,籃子拼到一半跑去通訊錄查個人再回來就沒了。刻意只放在 session
  // 記憶體:不進 localStorage、不進 Firestore(名單組合牽涉個資,不落地)。
  const [basket, setBasket] = useState(
    { terms: [], excluded: [], keepBlocked: false, includeUnknown: true, pastes: [] });
  const [loading, setLoading] = useState(false);
  const [loadErr, setLoadErr] = useState('');
  const topRef = useRef(null);

  // 固定頂欄(.admin-top)的實際高度會隨斷點/分頁列是否換行而變,寫死一個
  // padding-top 數字遲早會再度對不齊(這正是回歸 C 的成因)。改用
  // ResizeObserver 實測高度、寫進 CSS 變數 --admin-top-h,讓 .admin-shell
  // 的 padding-top 與 .tbl th 的 sticky top 永遠跟著真實高度走。
  useEffect(() => {
    const el = topRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const apply = () => {
      document.documentElement.style.setProperty('--admin-top-h', el.offsetHeight + 'px');
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 同一個 origin 上,workshop/board 會留下「匿名登入」session。匿名帳號沒有 email,
  // 若直接當成已登入,後台會跳過登入畫面、卡在一個沒有帳號可換的死路。
  // 因此只有帶 email 的帳號才算登入者。
  useEffect(() => window.fbAuth.onAuthStateChanged(
    (u) => setUser(u && u.email ? u : null)), []);

  const load = useCallback(async () => {
    setLoading(true); setLoadErr('');
    try {
      const grab = async (c) => (await window.fbDb.collection(c).get())
        .docs.map((d) => ({ id: d.id, ...d.data() }));
      const [e, s, r, st] = await Promise.all(
        ['events', 'subscribers', 'blockReasons', 'stats'].map(grab));
      setEvents(e); setSubs(s); setReasons(r); setStats(st);
      setDenied('');
    } catch (err) {
      // 只有 Firestore 規則明確拒絕(帳號不在白名單)才走「沒有存取權限」畫面。
      // 網路中斷、暫時性 Firestore 故障等其他錯誤如果也套用同一個畫面,
      // 會誤導使用者以為帳號被踢掉、去重新登入也沒用 —— 改成保留既有資料、
      // 顯示錯誤條 + 重新載入按鈕,不清掉畫面上已經有的東西。
      if (err && err.code === 'permission-denied') {
        setDenied(String(err.message || err));
      } else {
        setLoadErr(String((err && err.message) || err));
      }
    }
    setLoading(false);
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  // 手機瀏覽器(特別是 iOS Safari)常擋 popup;第三方 Cookie 政策也會讓它失效。
  // 因此 popup 失敗時改走 redirect —— 不然在手機上會是一個按了沒反應的死按鈕。
  const signIn = async () => {
    const p = new firebase.auth.GoogleAuthProvider();
    p.setCustomParameters({ prompt: 'select_account' });
    try {
      await window.fbAuth.signInWithPopup(p);
    } catch (e) {
      const code = (e && e.code) || '';
      if (code === 'auth/popup-blocked' ||
          code === 'auth/cancelled-popup-request' ||
          code === 'auth/operation-not-supported-in-this-environment') {
        try { await window.fbAuth.signInWithRedirect(p); return; }
        catch (e2) { setDenied(String((e2 && e2.message) || e2)); return; }
      }
      if (code === 'auth/popup-closed-by-user') return;   // 使用者自己關掉,不是錯誤
      setDenied(String((e && e.message) || e));
    }
  };

  // 走 redirect 回來時要把結果收掉,否則錯誤會靜默消失。
  useEffect(() => {
    if (!window.fbAuth.getRedirectResult) return;
    window.fbAuth.getRedirectResult().catch(
      (e) => setDenied(String((e && e.message) || e)));
  }, []);

  // 實際寫入 Firestore 的動作,由 BlockConfirmPanel 呼叫 —— 理由/二次確認的
  // 判斷都留在面板裡,這裡只管「照傳進來的值寫」+ 樂觀更新本地狀態。
  // 寫入失敗要 throw 出去,讓面板接住並顯示錯誤,不能在這裡吞掉。
  const applyBlock = useCallback(async (s, blocked, blockReasons) => {
    await window.fbDb.collection('subscribers').doc(s.id).set(
      { blocked, blockReasons }, { merge: true });
    setSubs((all) => all.map((x) => (x.id === s.id
      ? { ...x, blocked, blockReasons } : x)));
  }, []);

  const segs = useMemo(() => buildSegments(events, subs), [events, subs]);

  if (user === undefined) {
    return <div className="gate"><div className="empty" role="status" aria-live="polite">載入中…</div></div>;
  }

  if (!user) {
    return (
      <div className="gate">
        <div className="gate-card">
          <h1>好學生筆記 · 後台</h1>
          <p>文章點擊統計與電子報通訊錄。<br />此頁含個人資料,僅限授權帳號存取。</p>
          <button className="btn" onClick={signIn}>以 Google 帳號登入</button>
          {denied && <div className="err" role="alert">{denied}</div>}
        </div>
      </div>
    );
  }

  if (denied) {
    return (
      <div className="gate">
        <div className="gate-card">
          <h1>沒有存取權限</h1>
          <p>帳號 <b>{user.email}</b> 不在後台白名單內。<br />
             這是 Firestore 安全規則在伺服器端拒絕的,不是畫面隱藏。</p>
          <div className="row" style={{ justifyContent: 'center' }}>
            <button className="btn" onClick={signIn}>換一個帳號登入</button>
            <button className="btn ghost" onClick={() => window.fbAuth.signOut()}>登出</button>
          </div>
          <div className="err" role="alert">{denied}</div>
        </div>
      </div>
    );
  }

  const TABS = [
    ['roster', 'Contacts 通訊錄'],
    ['stats',  'Analytics 點擊統計'],
    ['export', 'Export 匯出'],
    ['events', 'Events 事件'],
    ['block',  'Blocked 封鎖區'],
  ];

  // 分頁列支援左右方向鍵切換(role=tablist 的標準鍵盤行為),並把焦點帶去
  // 新分頁的按鈕上,不然鍵盤使用者會不知道焦點跑去哪。
  const onTabsKeyDown = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    const idx = TABS.findIndex(([id]) => id === tab);
    const dir = e.key === 'ArrowRight' ? 1 : -1;
    const next = TABS[(idx + dir + TABS.length) % TABS.length][0];
    setTab(next);
    requestAnimationFrame(() => {
      const el = document.getElementById('tab-' + next);
      if (el) el.focus();
    });
  };

  return (
    <div>
      <div className="admin-top" ref={topRef}>
        <div className="admin-brand"><span>好學生筆記 · 後台</span></div>
        <div className="tabs" role="tablist" aria-label="後台分頁" onKeyDown={onTabsKeyDown}>
          {TABS.map(([id, label]) => (
            <button key={id} id={'tab-' + id} role="tab"
                    aria-selected={tab === id} aria-controls={'panel-' + id}
                    tabIndex={tab === id ? 0 : -1}
                    className={'tab ' + (tab === id ? 'on' : '')}
                    onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div className="admin-who">
          <span className="who-email">{user.email}</span>
          <button className="btn small ghost" onClick={() => window.fbAuth.signOut()}>登出</button>
        </div>
      </div>

      <div className="admin-shell">
        {loadErr && (
          <div className="err" role="alert" style={{ marginBottom: 20, maxWidth: 640 }}>
            資料讀取失敗:{loadErr}
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn small" onClick={load}>重新載入</button>
            </div>
          </div>
        )}
        {loading ? <div className="empty" role="status" aria-live="polite">載入資料中…</div> : (
          <div role="tabpanel" id={'panel-' + tab} aria-labelledby={'tab-' + tab}>
            {tab === 'roster' && <RosterTab segs={segs} events={events} reasons={reasons}
                                            subs={subs} onBlockConfirm={applyBlock} reload={load} />}
            {tab === 'stats'  && <StatsTab stats={stats} />}
            {tab === 'export' && <ExportTab segs={segs} events={events} subs={subs}
                                            basket={basket} setBasket={setBasket} />}
            {tab === 'events' && <EventsTab events={events} subs={subs} reload={load} />}
            {tab === 'block'  && <BlockTab subs={subs} reasons={reasons} reload={load} onBlockConfirm={applyBlock} />}
          </div>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
