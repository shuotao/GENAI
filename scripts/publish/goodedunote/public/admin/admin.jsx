/* admin.jsx — 好學生筆記 後台
   ────────────────────────────────────────────────────────────────────────
   保護模型:登入後所有讀寫都由 firestore.rules 的 admins/ 白名單把關。
   前端不做任何「藏起來」式的權限判斷 —— 非白名單帳號拿到的是 Firestore
   的 permission-denied,不是被 CSS 隱藏的畫面。

   資料載入策略:events(17)/subscribers(318)/blockReasons(6)/stats 一次抓完,
   之後全在前端篩選 —— 資料量小,換來零延遲的分眾切換。
   registrations(885 筆)刻意不預載,點開單一人員時才抓,避免無謂讀取。
*/
const { useState, useEffect, useMemo, useCallback } = React;

const CATS = {
  mcp:       { label: 'MCP 小聚',   tone: 'mcp' },
  slides:    { label: '演講資料',   tone: 'slides' },
  community: { label: '社群申請',   tone: 'community' },
};
const tone = (c) => (CATS[c] ? CATS[c].tone : 'other');
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

/* ── 分眾定義 ───────────────────────────────────────────────────────────────
   分眾一律是「對已載入資料的查詢」,不是另一份維護中的名單。
   新增一個事件 → 自動多一個分眾,不需要改這支程式。 */
function buildSegments(events, subs) {
  const month = ymNow();
  const inMonth = new Set(
    events.filter((e) => e.category === 'mcp' && (e.date || '').startsWith(month)).map((e) => e.id)
  );
  const has = (s, ids) => (s.eventIds || []).some((i) => ids.has(i));
  const byCat = (c) => subs.filter((s) => (s.categories || []).includes(c));

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
  segs.push({ id: 'blocked', name: '封鎖區', rows: subs.filter((s) => s.blocked) });
  return segs;
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
function RosterTab({ segs, events, reasons, onBlock }) {
  const [segId, setSegId] = useState('mcp');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const [regs, setRegs] = useState({});

  const seg = segs.find((s) => s.id === segId) || segs[0];
  const evName = useMemo(
    () => Object.fromEntries(events.map((e) => [e.id, e])), [events]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const r = needle
      ? seg.rows.filter((s) => (s.email || '').includes(needle) ||
                               (s.name || '').toLowerCase().includes(needle))
      : seg.rows;
    return [...r].sort((a, b) => String(b.lastSeenAt || '').localeCompare(String(a.lastSeenAt || '')));
  }, [seg, q]);

  const expand = useCallback(async (id) => {
    setOpen(open === id ? null : id);
    if (regs[id] || open === id) return;
    const snap = await window.fbDb.collection('subscribers').doc(id)
      .collection('registrations').get();
    setRegs((m) => ({ ...m, [id]: snap.docs.map((d) => d.data()) }));
  }, [open, regs]);

  return (
    <div>
      <div className="eyebrow">Contacts</div>
      <h2 className="admin-h2">電子報通訊錄</h2>
      <p className="admin-note">
        一人一筆(以正規化 email 為鍵),底下掛每一次報名紀錄。
        左側分眾全部是「查詢」而非另一份名單 —— 新增一個事件,分眾就自動反映,不需人工維護。
      </p>

      <div className="roster">
        <div>
          {segs.map((s) => (
            <button key={s.id} className={'seg ' + (s.id === segId ? 'on' : '')}
                    onClick={() => { setSegId(s.id); setOpen(null); }}>
              <span>{s.name}</span>
              <span className="seg-n">{s.rows.length}</span>
            </button>
          ))}
        </div>

        <div>
          <div className="row" style={{ marginBottom: 14 }}>
            <input className="inp" style={{ maxWidth: 300 }} placeholder="搜尋 email 或姓名…"
                   value={q} onChange={(e) => setQ(e.target.value)} />
            <span className="card-meta">{rows.length} 人</span>
          </div>
          {seg.hint && <div className="admin-note" style={{ marginBottom: 14 }}>ⓘ {seg.hint}</div>}

          {!rows.length ? <div className="card"><div className="empty">此分眾目前沒有人</div></div> : (
            <div className="card" style={{ padding: '6px 14px 14px' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Email</th><th>姓名</th><th>報過的場次</th><th>狀態</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <React.Fragment key={s.id}>
                      <tr>
                        <td className="mono">{s.email}</td>
                        <td>{s.name || <span style={{ color: 'var(--ink-faint)' }}>—</span>}</td>
                        <td>
                          {(s.categories || []).map((c) => (
                            <span key={c} className={'chip ' + tone(c)}>{catLabel(c)}</span>
                          ))}
                          <span className="card-meta"> {(s.eventIds || []).length} 場</span>
                        </td>
                        <td>
                          {s.blocked
                            ? (s.blockReasons || []).map((r) => (
                                <span key={r} className="chip block">
                                  {(reasons.find((x) => x.id === r) || {}).label || r}
                                </span>))
                            : <span className="card-meta">可寄送</span>}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button className="btn small ghost" onClick={() => expand(s.id)}>
                            {open === s.id ? '收合' : '明細'}
                          </button>{' '}
                          <button className="btn small ghost" onClick={() => onBlock(s)}>
                            {s.blocked ? '解封' : '封鎖'}
                          </button>
                        </td>
                      </tr>
                      {open === s.id && (
                        <tr>
                          <td colSpan={5} style={{ background: 'var(--paper-soft)' }}>
                            {!regs[s.id] ? <span className="card-meta">載入中…</span> : (
                              <div>
                                {regs[s.id]
                                  .sort((a, b) => String(a.eventDate).localeCompare(String(b.eventDate)))
                                  .map((r, i) => (
                                  <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                                    <span className={'chip ' + tone(r.category)}>
                                      {(evName[r.eventId] || {}).name || r.eventId}
                                    </span>
                                    <span className="card-meta"> {r.eventDate} </span>
                                    {(r.tickets || []).map((t) => (
                                      <span key={t} className="chip">{t}</span>))}
                                    {!!(r.ticketsRaw || []).length && (
                                      <div style={{ fontSize: 11.5, color: 'var(--ink-mute)', marginTop: 4 }}>
                                        原文:{r.ticketsRaw.join('｜')}
                                      </div>)}
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── 分頁:匯出 ─────────────────────────────────────────────────────────── */
function ExportTab({ segs }) {
  const [segId, setSegId] = useState('mcp');
  const seg = segs.find((s) => s.id === segId) || segs[0];
  // 匯出一律扣掉封鎖者 —— 封鎖區本身除外(那就是要看被擋下來的人)。
  const rows = segId === 'blocked' ? seg.rows : seg.rows.filter((s) => !s.blocked);
  const excluded = seg.rows.length - rows.length;

  const go = () => downloadCsv(
    `goodedunote_${segId}_${new Date().toISOString().slice(0, 10)}.csv`,
    [['email', 'name', 'categories', 'events', 'firstSeenAt', 'lastSeenAt', 'blocked', 'blockReasons'],
     ...rows.map((s) => [s.email, s.name || '', (s.categories || []).join(' '),
                         (s.eventIds || []).join(' '), s.firstSeenAt || '', s.lastSeenAt || '',
                         s.blocked ? 'Y' : '', (s.blockReasons || []).join(' ')])]);

  return (
    <div>
      <div className="eyebrow">Export</div>
      <h2 className="admin-h2">匯出名單</h2>
      <p className="admin-note">
        選一個分眾匯出 CSV,貼進任何寄送平台即可。檔案帶 UTF-8 BOM,Excel 直接開不會亂碼。
        除「封鎖區」外,匯出一律自動扣除被封鎖者。
      </p>
      <div className="card" style={{ maxWidth: 560 }}>
        <div className="card-title">選擇分眾</div>
        {segs.map((s) => (
          <button key={s.id} className={'seg ' + (s.id === segId ? 'on' : '')}
                  onClick={() => setSegId(s.id)}>
            <span>{s.name}</span><span className="seg-n">{s.rows.length}</span>
          </button>
        ))}
        <div className="stat-row" style={{ marginTop: 22 }}>
          <div>
            <div className="stat-n">{rows.length}</div>
            <div className="stat-lab">將匯出</div>
          </div>
          {excluded > 0 && (
            <div>
              <div className="stat-n" style={{ color: 'var(--ink-faint)' }}>{excluded}</div>
              <div className="stat-lab">已扣除封鎖</div>
            </div>)}
        </div>
        <button className="btn" onClick={go} disabled={!rows.length}>下載 CSV</button>
      </div>
    </div>
  );
}

/* ── 分頁:事件管理 ─────────────────────────────────────────────────────── */
function EventsTab({ events, reload }) {
  const [f, setF] = useState({ id: '', name: '', category: 'mcp', date: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

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
    await window.fbDb.collection('events').doc(id).set({ category }, { merge: true });
    await reload();
  };

  return (
    <div>
      <div className="eyebrow">Events</div>
      <h2 className="admin-h2">報名種類 / 事件管理</h2>
      <p className="admin-note">
        每一個「報名種類」就是這裡的一筆事件。要開新課程種類:新增一筆、給它一個分類代碼,
        通訊錄與匯出頁就會自動多出對應分眾 —— 不需要改任何程式。
        改既有事件的分類也會即時反映在分眾上。
      </p>

      <div className="card" style={{ maxWidth: 620, marginBottom: 26 }}>
        <div className="card-title">新增事件</div>
        <div className="row" style={{ marginBottom: 10 }}>
          <input className="inp" style={{ maxWidth: 220 }} placeholder="事件代碼(如 mcp-2026-09)"
                 value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} />
          <input className="inp" style={{ maxWidth: 130 }} placeholder="日期 2026-09-20"
                 value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        </div>
        <div className="row" style={{ marginBottom: 14 }}>
          <input className="inp" style={{ maxWidth: 220 }} placeholder="顯示名稱"
                 value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <input className="inp" style={{ maxWidth: 130 }} placeholder="分類代碼"
                 value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} />
        </div>
        <button className="btn" onClick={save} disabled={busy}>{busy ? '儲存中…' : '新增'}</button>
        {err && <div className="err">{err}</div>}
      </div>

      <div className="card" style={{ padding: '6px 14px 14px' }}>
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
                  <input className="inp" style={{ maxWidth: 130, fontSize: 12 }}
                         defaultValue={e.category}
                         onBlur={(ev) => ev.target.value !== e.category && setCat(e.id, ev.target.value.trim())} />
                </td>
                <td className="num">{e.importedCount != null ? e.importedCount : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── 分頁:封鎖區 ───────────────────────────────────────────────────────── */
function BlockTab({ subs, reasons, reload, onBlock }) {
  const blocked = subs.filter((s) => s.blocked);
  const [nr, setNr] = useState({ id: '', label: '' });
  const [err, setErr] = useState('');

  const addReason = async () => {
    if (!nr.id.trim() || !nr.label.trim()) { setErr('代碼與標籤為必填'); return; }
    setErr('');
    await window.fbDb.collection('blockReasons').doc(nr.id.trim())
      .set({ label: nr.label.trim(), builtin: false }, { merge: true });
    setNr({ id: '', label: '' });
    await reload();
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
        <div className="row">
          <input className="inp" style={{ maxWidth: 170 }} placeholder="代碼(如 spam-trap)"
                 value={nr.id} onChange={(e) => setNr({ ...nr, id: e.target.value })} />
          <input className="inp" style={{ maxWidth: 170 }} placeholder="顯示標籤"
                 value={nr.label} onChange={(e) => setNr({ ...nr, label: e.target.value })} />
          <button className="btn small" onClick={addReason}>新增理由</button>
        </div>
        {err && <div className="err">{err}</div>}
      </div>

      {!blocked.length ? <div className="card"><div className="empty">目前沒有被封鎖的聯絡人</div></div> : (
        <div className="card" style={{ padding: '6px 14px 14px' }}>
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
                  <td style={{ fontSize: 11, color: 'var(--ink-mute)', maxWidth: 300 }}>
                    {(s.blockNote || '').split('\n').slice(0, 2).join(' / ') || '—'}
                  </td>
                  <td><button className="btn small ghost" onClick={() => onBlock(s)}>解封</button></td>
                </tr>
              ))}
            </tbody>
          </table>
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

  // 同一個 origin 上,workshop/board 會留下「匿名登入」session。匿名帳號沒有 email,
  // 若直接當成已登入,後台會跳過登入畫面、卡在一個沒有帳號可換的死路。
  // 因此只有帶 email 的帳號才算登入者。
  useEffect(() => window.fbAuth.onAuthStateChanged(
    (u) => setUser(u && u.email ? u : null)), []);

  const load = useCallback(async () => {
    setLoading(true); setDenied('');
    try {
      const grab = async (c) => (await window.fbDb.collection(c).get())
        .docs.map((d) => ({ id: d.id, ...d.data() }));
      const [e, s, r, st] = await Promise.all(
        ['events', 'subscribers', 'blockReasons', 'stats'].map(grab));
      setEvents(e); setSubs(s); setReasons(r); setStats(st);
    } catch (err) {
      // 非白名單帳號會走到這裡 —— 是 Firestore 規則擋下的,不是前端藏起來的。
      setDenied(String(err && err.message ? err.message : err));
    }
    setLoading(false);
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const signIn = async () => {
    const p = new firebase.auth.GoogleAuthProvider();
    p.setCustomParameters({ prompt: 'select_account' });
    try { await window.fbAuth.signInWithPopup(p); }
    catch (e) { setDenied(String(e.message || e)); }
  };

  const toggleBlock = useCallback(async (s) => {
    const next = !s.blocked;
    const reasons_ = next
      ? (s.blockReasons && s.blockReasons.length ? s.blockReasons : ['not-target'])
      : [];
    await window.fbDb.collection('subscribers').doc(s.id).set(
      { blocked: next, blockReasons: reasons_ }, { merge: true });
    setSubs((all) => all.map((x) => (x.id === s.id
      ? { ...x, blocked: next, blockReasons: reasons_ } : x)));
  }, []);

  const segs = useMemo(() => buildSegments(events, subs), [events, subs]);

  if (user === undefined) return <div className="gate"><div className="empty">載入中…</div></div>;

  if (!user) {
    return (
      <div className="gate">
        <div className="gate-card">
          <h1>好學生筆記 · 後台</h1>
          <p>文章點擊統計與電子報通訊錄。<br />此頁含個人資料,僅限授權帳號存取。</p>
          <button className="btn" onClick={signIn}>以 Google 帳號登入</button>
          {denied && <div className="err">{denied}</div>}
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
          <div className="err">{denied}</div>
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

  return (
    <div>
      <div className="admin-top">
        <div className="admin-brand">好學生筆記 · 後台</div>
        <div className="tabs">
          {TABS.map(([id, label]) => (
            <button key={id} className={'tab ' + (tab === id ? 'on' : '')}
                    onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div className="admin-who">
          <span>{user.email}</span>
          <button className="btn small ghost" onClick={() => window.fbAuth.signOut()}>登出</button>
        </div>
      </div>

      <div className="admin-shell">
        {loading ? <div className="empty">載入資料中…</div> : (
          <>
            {tab === 'roster' && <RosterTab segs={segs} events={events} reasons={reasons} onBlock={toggleBlock} />}
            {tab === 'stats'  && <StatsTab stats={stats} />}
            {tab === 'export' && <ExportTab segs={segs} />}
            {tab === 'events' && <EventsTab events={events} reload={load} />}
            {tab === 'block'  && <BlockTab subs={subs} reasons={reasons} reload={load} onBlock={toggleBlock} />}
          </>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
