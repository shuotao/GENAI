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
  // 名單軌跡分眾:來自 GWS 的 data/*.txt。這些不是「報名」,是「曾在哪份名單上」,
  // 因此獨立成一組,不與報名分眾混在一起。
  const onList = (label) => subs.filter((s) => (s.lists || []).includes(label));
  [['永久收件人', '永久收件人'],
   ['從未出席', '從未出席'],
   ['手動補入', '手動補入']].forEach(([label, name]) => {
    const rows = onList(label);
    if (rows.length) segs.push({ id: 'list:' + label, name, rows, group: 'list' });
  });
  const nl = [...new Set(subs.flatMap((s) => (s.lists || [])
    .filter((l) => l.startsWith('電子報'))))].sort();
  nl.forEach((label) => segs.push({
    id: 'list:' + label, name: label, rows: onList(label), group: 'list' }));

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
        lists: FV.arrayUnion('手動補入'),
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
                 儲存會<b>合併</b>而不是新增一筆:補上「手動補入」軌跡
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

/* ── 分頁:匯出 ─────────────────────────────────────────────────────────── */
function ExportTab({ segs, events }) {
  const [segId, setSegId] = useState('mcp');
  const [emailOnly, setEmailOnly] = useState(false);
  const [sep, setSep] = useState(', ');
  const [copied, setCopied] = useState(false);
  const seg = segs.find((s) => s.id === segId) || segs[0];
  // 匯出一律扣掉封鎖者與測試位址 —— 封鎖區本身除外(那就是要看被擋下來的人)。
  const rows = segId === 'blocked'
    ? seg.rows
    : seg.rows.filter((s) => !s.blocked && !s.testAddress);
  const excluded = seg.rows.length - rows.length;
  // categories 欄同 RosterTab,一律從 events 即時推導,不讀過期的 s.categories。
  const eventById = useMemo(
    () => Object.fromEntries(events.map((e) => [e.id, e])), [events]);

  const go = () => downloadCsv(
    `goodedunote_${segId}_${new Date().toISOString().slice(0, 10)}.csv`,
    [['email', 'name', 'categories', 'events', 'lists', 'firstSeenAt', 'lastSeenAt',
      'blocked', 'blockReasons'],
     ...rows.map((s) => [s.email, s.name || '', effectiveCats(s, eventById).join(' '),
                         (s.eventIds || []).join(' '), (s.lists || []).join('｜'),
                         s.firstSeenAt || '', s.lastSeenAt || '',
                         s.blocked ? 'Y' : '', (s.blockReasons || []).join(' ')])]);

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

  return (
    <div>
      <div className="eyebrow">Export</div>
      <h2 className="admin-h2">匯出名單</h2>
      <p className="admin-note">
        選一個分眾匯出 CSV,貼進任何寄送平台即可。檔案帶 UTF-8 BOM,Excel 直接開不會亂碼。
        除「封鎖區」外,匯出一律自動扣除<b>被封鎖者</b>與<b>測試位址</b>。
      </p>
      <div className="export-grid">
      <div className="card">
        <div className="card-title">選擇分眾</div>
        {segs.map((s, i) => (
          <React.Fragment key={s.id}>
            {s.group === 'list' && (i === 0 || segs[i - 1].group !== 'list') && (
              <div className="eyebrow" style={{ marginTop: 18, marginBottom: 6 }}>
                名單軌跡 · from GWS
              </div>)}
            <button className={'seg ' + (s.id === segId ? 'on' : '')}
                    onClick={() => setSegId(s.id)}>
              <span>{s.name}</span><span className="seg-n">{s.rows.length}</span>
            </button>
          </React.Fragment>
        ))}
        <div className="stat-row" style={{ marginTop: 22 }}>
          <div>
            <div className="stat-n">{rows.length}</div>
            <div className="stat-lab">將匯出</div>
          </div>
          {excluded > 0 && (
            <div>
              {/* 這個數字告訴使用者「有東西被扣掉了」,是操作相關資訊,
                  用 ink-faint 對比太低容易被忽略。 */}
              <div className="stat-n" style={{ color: 'var(--ink-mute)' }}>{excluded}</div>
              <div className="stat-lab">已扣除封鎖 / 測試</div>
            </div>)}
        </div>
        <div className="row">
          <button className="btn" onClick={go} disabled={!rows.length}>下載 CSV</button>
          <button className={'btn ' + (emailOnly ? '' : 'ghost')}
                  onClick={() => setEmailOnly(!emailOnly)} disabled={!rows.length}>
            Email Only
          </button>
        </div>
      </div>

      {emailOnly && (
        <div className="card">
          <div className="card-title">
            Email Only
            <span className="card-meta">{rows.length} 個位址</span>
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
                    value={emailText} rows={16}
                    onFocus={(e) => e.target.select()} />
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" onClick={copy} aria-live="polite">{copied ? '已複製 ✓' : '複製全部'}</button>
            <span className="card-meta" role="status" aria-live="polite">
              {copied ? '已複製到剪貼簿' : `${emailText.length.toLocaleString()} 字元`}
            </span>
          </div>
        </div>)}
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
            {tab === 'export' && <ExportTab segs={segs} events={events} />}
            {tab === 'events' && <EventsTab events={events} subs={subs} reload={load} />}
            {tab === 'block'  && <BlockTab subs={subs} reasons={reasons} reload={load} onBlockConfirm={applyBlock} />}
          </div>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
