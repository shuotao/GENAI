#!/usr/bin/env python3
"""把 GWS 的報名資料批次匯入 goodedunote 後台的 Firestore 名冊。

設計要點
────────
1. **GWS 全程唯讀。** GWS 有 BLOCKING scope guard(禁止在其中引入資料庫/web
   service),本工具只讀它的 data/,不在 GWS 內寫任何檔。

2. **正規化語義不重新發明。** 直接 import GWS 的 scripts/_common.py,
   normalize_email / load_blacklist / blacklist_hit 用的是同一份程式碼。
   自己重寫一份 regex 遲早會漂移,而漂移的後果是「黑名單靜默失效」。

3. **Round 11 規則:raw 與 corrected 兩種形式都留、都比對。**
   email_corrections.json 會把黑名單上的位址映射到乾淨位址;只存修正後的形式,
   會讓被封鎖的人重新收到信。rawEmails[] 就是為此存在。

4. **報名選項是複選且很髒**(46 種相異值,含匯款備註與 GitHub 網址,
   且價格逐月變動:第一次參加的老師 4,000→4,300→…→6,000)。
   因此 ticket 一律**比對前綴**、存成陣列,並原文照存 ticketsRaw。

用法:
    python3 scripts/import_roster.py --dry-run
    python3 scripts/import_roster.py
    python3 scripts/import_roster.py --rollback 20260901-153000
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gnote_db  # noqa: E402

DEFAULT_GWS = pathlib.Path.home() / "Desktop" / "GWS"

# ── 事件定義表 ──────────────────────────────────────────────────────────────
# 這張表是「哪個檔案 = 哪一場活動 = 哪個分眾」的唯一宣告處,刻意寫死而非猜測,
# 因為分類錯誤會直接導致電子報寄錯人。要改分類:在後台「事件管理」改即可。
#
# eventDate 對月報名表用「該月 1 日」——form 本身就代表那個月的小聚,
# 這讓「當月報名」的查詢在語義上精確(而非拿報名時間近似)。
MONTHLY = [  # (stem, eventId, 顯示名稱, 年月)
    ("jan",    "mcp-2026-01", "MCP 小聚 · 2026 年 1 月", "2026-01"),
    ("feb",    "mcp-2026-02", "MCP 小聚 · 2026 年 2 月", "2026-02"),
    ("march",  "mcp-2026-03", "MCP 小聚 · 2026 年 3 月", "2026-03"),
    ("april",  "mcp-2026-04", "MCP 小聚 · 2026 年 4 月", "2026-04"),
    ("may",    "mcp-2026-05", "MCP 小聚 · 2026 年 5 月", "2026-05"),
    ("june",   "mcp-2026-06", "MCP 小聚 · 2026 年 6 月", "2026-06"),
    ("july",   "mcp-2026-07", "MCP 小聚 · 2026 年 7 月", "2026-07"),
    ("august", "mcp-2026-08", "MCP 小聚 · 2026 年 8 月", "2026-08"),
]

EXTRA = [  # (檔名, eventId, 顯示名稱, category, eventDate)
    ("extra_1LdXc80L9SzPyfHawxJEChOwPQddS_MIKUfLlCthgZ2o_responses.jsonl",
     "mcp-2026-08-22-kaohsiung", "Revit MCP 讀書會 · 8/22 高雄現場小聚", "mcp", "2026-08-22"),
    ("extra_1DaOkIzzu1l7SXdZG8zpURYXl3E6rkHJwsUv7HfzWeAk_responses.jsonl",
     "mcp-2026-08-22-online", "Revit MCP 讀書會 · 8/22 線上場", "mcp", "2026-08-22"),
    ("extra_1avLgzPKQkFUKlSxK0q6hlFFDKq-y8R5foU3AdnGMQDQ.jsonl",
     "talk-iso19650-2025-07", "ISO 19650 線上分享 · 2025/07/25", "slides", "2025-07-25"),
    ("extra_1GkG5nToB3hgcMk1CP3qlxL5yWWtU2Qj0t5eSk4Vxq0M.jsonl",
     "talk-iso19650-3-2025-08", "ISO 19650-3 線上分享 · 2025/08/22", "slides", "2025-08-22"),
    ("extra_1_CxGAEZfdorhmtglyLEWYsbiWh7wTw_IgNNcDlNea48.jsonl",
     "talk-au2025", "AU 2025 線上討論會", "slides", "2025-09-14"),
    ("extra_1H5htjittLYx-SptsvM4D0gghxNWewiysJV8n6sj03tY.jsonl",
     "talk-online-reading-2025-09", "線上導讀計劃", "slides", "2025-09-16"),
    ("extra_1azFvWsZKPYqYZHjQQpKiIb49LMcv7KyN8GIPvjg5Lto.jsonl",
     "talk-share-2025-q4", "線上分享主講場 · 2025 Q4", "slides", "2025-12-30"),
    ("extra_1takjI0Bp40W7HLrMY0yXRTAaPOwFWpOiksXtX3T_6lU.jsonl",
     "talk-architect-assoc-2022", "建築師公會演講活動 · 2022/08", "slides", "2022-08-12"),
    # 「MCP 功能開發意願書」——參與意願申請,最接近「社群申請」。
    # 若歸類不合意,在後台「事件管理」改 category 即可,不必重跑匯入。
    ("intention_responses.jsonl",
     "community-mcp-intention", "MCP 功能開發意願書", "community", "2026-02-12"),
]

# SSoT 違規的重複檔(GEMINI.md 明令不得建立 *_new.jsonl),一律跳過。
SKIP_FILES = {"april_responses_live.jsonl", "april_responses_new.jsonl",
              "july_responses_live.jsonl", "june_responses_live.jsonl",
              "march_responses_live.jsonl", "may_responses_live.jsonl",
              "latest_april_50.jsonl", "mcp_dev_responses_new.jsonl"}

# ── 報名選項 → ticket 類型 ─────────────────────────────────────────────────
# 一律比對「前綴」:價格逐月變動,比對整串會在每次調價時靜默失配。
TICKET_PREFIXES = [
    ("我要參加線上zoom",              "online"),
    ("我要參加線上場",                "online"),
    ("線上參加",                      "online"),
    ("我要參加現場小樹屋",            "onsite"),
    ("現場小樹屋",                    "onsite"),
    ("我要參加現場高雄小聚",          "onsite"),
    ("我要參加「現場」活動",          "onsite"),
    ("我是第一次參加的老師",          "first-time-teacher"),
    ("我是原來 MCP 參加老師",         "returning-teacher"),
    ("我是本次的分享老師",            "speaker"),
    ("我有提ISSUE",                   "free-contributor"),
    ("我有去 HJPLUS",                 "free-contributor"),
    ("我有做作業",                    "free-contributor"),
    ("我在聚會後在個人社群分享",      "free-social-share"),
    ("我要分享illoca.com",            "free-social-share"),
    ("我還沒但我想要課金學",          "paid-learner"),
    ("課金組",                        "paid-learner"),
    ("我已經完成REVIT MCP的部署",     "deployed"),
    ("我已經完成語言模型",            "tested"),
    ("我還沒有進行但是我想要加入每月共讀", "reading-club"),
]


# ── 名單檔來源 ──────────────────────────────────────────────────────────────
# responses/*.jsonl 給的是「報名事件」;data/*.txt 給的是另一種東西 ——
# 「這個人曾出現在哪一份名單上」。兩者不可混為一談:名單成員不是報名紀錄。
# 因此名單以 subscriber.lists[] 記錄軌跡,而不是偽造一筆 registration。
#
# 刻意排除的檔案:
#   union_audience.txt / derived_audience.txt —— 純機器推導的中間產物,
#     成員身分不帶新資訊(且 derived 的表頭就寫著它是算出來的)。
#   exclude_829_registered.txt —— 一次性的客戶指示,不是名單屬性。
LIST_SOURCES = [  # (檔名, 標籤, 是否為測試位址)
    ("audience_241.txt",                "電子報 nl24 名單",            False),
    ("audience_26.txt",                 "電子報 nl26 名單",            False),
    ("audience_27.txt",                 "電子報 nl27 名單",            False),
    ("audience_28.txt",                 "電子報 nl28 名單",            False),
    ("audience_28_resend.txt",          "電子報 nl28 補寄",            False),
    ("audience_31.txt",                 "電子報 nl31 名單",            False),
    ("audience_33.txt",                 "電子報 nl33 名單",            False),
    ("audience_33_resend.txt",          "電子報 nl33 補寄",            False),
    ("supp_audience.txt",               "手動補入",                    False),
    ("supp_xxzz.txt",                   "手動補入(第二批)",          False),
    ("extra_permanent_recipients.txt",  "永久收件人",                  False),
    ("mcp_1_to_8_emails.txt",           "MCP 1–8 月累積快照",          False),
    ("non_participants.txt",            "從未出席",                    False),
    # GWS 自己的 CLOSEOUT-roster.md 記載這份「雙向都錯」(多 16、少 11),
    # 所以只留軌跡,標籤明說不可信,絕不拿它當事實做任何篩選。
    ("clean_not_registered_emails.txt", "未報名清單(GWS 標記不可信)", False),
    ("test_audience.txt",               "測試位址",                    True),
    # 抑制清單也建成聯絡人:否則「只出現在黑名單、從未報名」的位址在後台
    # 封鎖區看不到,就無從檢視理由、也無法解封。
    ("blacklist.txt",                   "來自黑名單",                  False),
    ("bounced.txt",                     "來自退信清單",                False),
    ("unsubscribed.txt",                "來自退訂清單",                False),
]


def load_gws_common(gws: pathlib.Path):
    """載入 GWS 的 _common.py 當模組 —— 正規化語義的 SSoT。"""
    path = gws / "scripts" / "_common.py"
    if not path.exists():
        sys.exit(f"[import_roster] 找不到 GWS 共用模組:{path}\n"
                 f"  用 --gws 指定 GWS 專案根目錄。")
    spec = importlib.util.spec_from_file_location("gws_common", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def classify_tickets(values: list[str]) -> list[str]:
    out = []
    for v in values:
        s = v.strip()
        hit = next((t for pre, t in TICKET_PREFIXES if s.startswith(pre)), None)
        out.append(hit or "other")
    return sorted(set(out))


def parse_file(path: pathlib.Path, C) -> list[dict]:
    """解析一份 Forms 匯出。比 GWS 的 parse_response_records 多留
    respondentEmail / responseId —— 後台要能追溯到單筆回覆。"""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        responses = payload.get("responses", [payload]) if isinstance(payload, dict) else []
        for r in responses:
            if not isinstance(r, dict):
                continue
            answers = r.get("answers", {}) or {}
            vals = {k: [str(a.get("value", "")).strip()
                        for a in (v.get("textAnswers", {}) or {}).get("answers", [])
                        if isinstance(a, dict) and a.get("value")]
                    for k, v in answers.items() if isinstance(v, dict)}

            typed = (vals.get(C.FALLBACK_EMAIL_ID) or [""])[0]
            if not typed:  # 舊表沒有固定 question id,退而找長得像 email 的答案
                for values in vals.values():
                    for v in values:
                        if C._EMAIL_PATTERN.search(v.lower()):
                            typed = v
                            break
                    if typed:
                        break
            verified = str(r.get("respondentEmail", "") or "").strip()

            name = (vals.get(C.FALLBACK_NAME_ID) or [""])[0]
            if not name:
                for values in vals.values():
                    for v in values:
                        if ("@" not in v and len(v) <= 12
                                and not any(k in v for k in C._NAME_EXCLUSIONS)):
                            name = v
                            break
                    if name:
                        break

            desc = vals.get(C.FALLBACK_DESCRIPTION_ID, [])
            if not desc:  # extra_* 用不同 question id:除姓名/email 外的答案都算選項
                desc = [v for k, values in vals.items() for v in values
                        if k not in (C.FALLBACK_NAME_ID, C.FALLBACK_EMAIL_ID)
                        and "@" not in v and v != name]

            records.append({
                "typed": typed, "verified": verified,
                "name": C.normalize_name(name),
                "desc": desc,
                "responseId": r.get("responseId", ""),
                "createTime": r.get("createTime", ""),
            })
    return records


def load_tokens(path: pathlib.Path) -> set[str]:
    """讀抑制清單。比照 GWS load_blacklist:以 [\\s/]+ 切,一行可含多個 token,
    且 token 不保證是合法 email(黑名單刻意收容格式壞掉的字串)。"""
    if not path.exists():
        return set()
    tokens = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens.update(t.lower() for t in re.split(r"[\s/]+", line) if t)
    return tokens


def blacklist_notes(path: pathlib.Path) -> str:
    """把 blacklist.txt 的 # 註解原文留下 —— 理由是散文,不可有損轉換。"""
    if not path.exists():
        return ""
    return "\n".join(l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                     if l.strip().startswith("#"))


def build(gws: pathlib.Path, C):
    """讀 GWS,建出 events 與 subscribers 兩張表(純記憶體,未寫入)。"""
    resp = gws / "data" / "responses"
    events, people = {}, {}
    per_event_rows = collections.Counter()

    def ingest(path, event_id, name, category, event_date):
        if not path.exists():
            print(f"  [warn] 找不到 {path.name},略過", file=sys.stderr)
            return
        rows = parse_file(path, C)
        per_event_rows[event_id] = len(rows)
        events[event_id] = {"name": name, "category": category, "date": event_date,
                            "source": path.name, "importedCount": len(rows)}
        for r in rows:
            # Round 11:verified 優先(Google 掛保證),但 typed 也要留著比對抑制清單
            key = C.normalize_email(r["verified"] or r["typed"])
            if not key:
                continue
            p = people.setdefault(key, {
                "email": key, "rawEmails": set(), "verifiedEmail": "", "name": "",
                "eventIds": set(), "categories": set(), "regs": [],
                "firstSeenAt": "", "lastSeenAt": "",
            })
            for raw in (r["typed"], r["verified"]):
                if raw:
                    p["rawEmails"].add(raw.strip().lower())
            if r["verified"]:
                p["verifiedEmail"] = r["verified"].strip().lower()
            if r["name"] and not p["name"]:
                p["name"] = r["name"]
            p["eventIds"].add(event_id)
            p["categories"].add(category)
            t = r["createTime"]
            if t:
                p["firstSeenAt"] = min(p["firstSeenAt"] or t, t)
                p["lastSeenAt"] = max(p["lastSeenAt"], t)
            p["regs"].append({
                "eventId": event_id, "category": category, "eventDate": event_date,
                "tickets": classify_tickets(r["desc"]), "ticketsRaw": r["desc"],
                "responseId": r["responseId"], "createTime": t,
            })

    for stem, eid, label, ym in MONTHLY:
        f = resp / f"{stem}_responses.jsonl"
        if f.name in SKIP_FILES:
            continue
        ingest(f, eid, label, "mcp", f"{ym}-01")
    for fname, eid, label, cat, date in EXTRA:
        ingest(resp / fname, eid, label, cat, date)

    return events, people, per_event_rows


def apply_blocks(people, gws, C):
    """套用三份抑制清單。三者語義不可互換,故分成三個理由。"""
    data = gws / "data"
    lists = [("email-invalid", load_tokens(data / "blacklist.txt")),
             ("bounced",       load_tokens(data / "bounced.txt")),
             ("unsubscribed",  load_tokens(data / "unsubscribed.txt"))]
    note = blacklist_notes(data / "blacklist.txt")
    tally = collections.Counter()
    for key, p in people.items():
        reasons = []
        for reason, tokens in lists:
            if not tokens:
                continue
            # 保守方向:key 或任一 raw 形式命中,即封鎖
            if key in tokens or any(r in tokens for r in p["rawEmails"]):
                reasons.append(reason)
        p["blocked"] = bool(reasons)
        p["blockReasons"] = reasons
        p["blockNote"] = note if "email-invalid" in reasons else ""
        for r in reasons:
            tally[r] += 1
    return tally


def warn_block_divergence(db, people) -> int:
    """比對「後台目前的封鎖狀態」與「這次匯入會寫入的封鎖狀態」,把差異印出來。

    為什麼需要:GWS 的 blacklist/bounced/unsubscribed 是抑制清單的權威來源,
    所以匯入覆寫 blocked 是刻意的。但如果有人在後台手動解封,重跑匯入會把他
    封回去 —— 那個「回去」如果是靜默的,就會變成一個沒人知道自己按過的決定
    被無聲推翻。這裡不阻擋,只確保它被看見。
    """
    current = {d.id: d.to_dict() for d in db.collection("subscribers").stream()}
    if not current:
        return 0
    diffs = []
    for key, p in people.items():
        was = bool(current.get(key, {}).get("blocked"))
        now = bool(p["blocked"])
        if was != now:
            diffs.append((key, was, now))
    if not diffs:
        print("  封鎖狀態:後台與本次匯入一致,無覆寫")
        return 0
    print(f"\n  ⚠️ 封鎖狀態有 {len(diffs)} 筆差異,匯入會以 GWS 的抑制清單為準覆寫:")
    for key, was, now in sorted(diffs):
        mask = f"{key[:3]}***@{key.split('@')[-1]}" if "@" in key else key[:3] + "***"
        arrow = "解封 → 封鎖" if now else "封鎖 → 解封"
        print(f"     {mask:<28} 後台{'封鎖' if was else '未封鎖'} / 匯入{'封鎖' if now else '未封鎖'}  ({arrow})")
    print("     若其中有你在後台刻意做的決定,請先改 GWS 的 blacklist/bounced/unsubscribed,")
    print("     否則這次匯入會把它推翻。")
    return len(diffs)


def write(db, events, people, batch_id, dry_run):
    from google.cloud import firestore as fs
    if dry_run:
        return
    wrote = 0

    def flush(batch, n):
        if n:
            gnote_db.commit(batch)
        return db.batch(), 0

    batch, n = db.batch(), 0
    for eid, ev in events.items():
        batch.set(db.collection("events").document(eid),
                  {**ev, "importBatch": batch_id, "createdAt": fs.SERVER_TIMESTAMP}, merge=True)
        n += 1
    batch, n = flush(batch, n)

    for key, p in people.items():
        doc = db.collection("subscribers").document(key)
        # 後台是活的:使用者會手動新增聯絡人、貼標籤、改封鎖。整個陣列覆寫會把
        # 那些改動靜默洗掉(2026-09-01 實例:後台手動加的 3 位,其「後台手動新增」
        # 標籤會被匯入算出來的 lists 換掉)。所以:
        #   lists  → ArrayUnion,只補不刪。名單軌跡本質是「曾經在某份名單上」,
        #            是歷史事實,不會因為新的匯入而變成假,append-only 才對。
        #   tags   → 完全不碰。那是純後台欄位,匯入沒有任何話語權。
        #   name   → 只在匯入有值時才寫,不用空字串蓋掉後台填的姓名。
        payload = {
            "email": p["email"], "rawEmails": fs.ArrayUnion(sorted(p["rawEmails"])),
            "verifiedEmail": p["verifiedEmail"],
            "eventIds": fs.ArrayUnion(sorted(p["eventIds"])),
            "categories": fs.ArrayUnion(sorted(p["categories"])),
            "firstSeenAt": p["firstSeenAt"], "lastSeenAt": p["lastSeenAt"],
            "blocked": p["blocked"], "blockReasons": p["blockReasons"],
            "blockNote": p["blockNote"], "importBatch": batch_id,
            "lists": fs.ArrayUnion(sorted(p.get("lists", ()))),
            "testAddress": bool(p.get("testAddress")),
        }
        if p["name"]:
            payload["name"] = p["name"]
        batch.set(doc, payload, merge=True)
        n += 1
        for reg in p["regs"]:
            # 冪等鍵:同一人同一場同一筆回覆只會有一份
            rid = f'{reg["eventId"]}__{reg["responseId"] or reg["createTime"]}'
            batch.set(doc.collection("registrations").document(rid),
                      {**reg, "importBatch": batch_id}, merge=True)
            n += 1
            if n >= 400:
                batch, n = flush(batch, n)
                wrote += 400
        if n >= 400:
            batch, n = flush(batch, n)
            wrote += 400
    flush(batch, n)


def collected_names(gws: pathlib.Path, C) -> dict:
    """reports/collected_contacts.json 是唯一帶乾淨 {name,email,source} 結構的報告檔,
    拿來替「只出現在名單檔、沒有報名紀錄」的聯絡人補姓名。
    同目錄其他 *.md 報告含未遮蔽的姓名+email 表格,一律不碰。"""
    p = gws / "data" / "reports" / "collected_contacts.json"
    if not p.exists():
        return {}
    out = {}
    for r in json.loads(p.read_text(encoding="utf-8")):
        e = C.normalize_email(r.get("email", ""))
        if e and r.get("name"):
            out.setdefault(e, C.normalize_name(r["name"]))
    return out


def ingest_lists(people: dict, gws: pathlib.Path, C) -> dict:
    """把 data/*.txt 名單的成員身分併進 people。

    名單檔只有 email(無姓名/無日期/無場次),所以它補的是「軌跡」不是「事件」:
    寫進 subscriber.lists[],並為只存在於名單、從未報名過的人建立聯絡人記錄。
    """
    names = collected_names(gws, C)
    tally = collections.Counter()
    created = 0
    for fname, label, is_test in LIST_SOURCES:
        path = gws / "data" / fname
        if not path.exists():
            print(f"  [warn] 找不到名單 {fname},略過", file=sys.stderr)
            continue
        for token in load_tokens(path):
            key = C.normalize_email(token)
            if not key:
                continue          # 黑名單那類「根本不是 email」的壞字串
            p = people.get(key)
            if p is None:
                p = people[key] = {
                    "email": key, "rawEmails": set(), "verifiedEmail": "",
                    "name": names.get(key, ""), "eventIds": set(), "categories": set(),
                    "regs": [], "firstSeenAt": "", "lastSeenAt": "", "lists": set(),
                }
                created += 1
            p.setdefault("lists", set()).add(label)
            p["rawEmails"].add(token)
            if is_test:
                p["testAddress"] = True
            tally[label] += 1
    for p in people.values():
        p.setdefault("lists", set())
        p.setdefault("testAddress", False)
    print(f"\n=== 名單軌跡({len(LIST_SOURCES)} 份檔案)===")
    for _, label, _ in LIST_SOURCES:
        print(f"  {label:<30} {tally[label]:>4} 人")
    print(f"  ── 其中只存在於名單、無報名紀錄而新建的聯絡人:{created} 人")
    return tally


def reconcile(gws: pathlib.Path, C, people) -> int:
    """對帳:把本工具的資料模型套上 GWS 那條減法鏈,和 GWS 自己的權威 stats 比。

    為什麼要同口徑處理:GWS 的集合刻意同時收 raw 與 corrected 兩種形式
    (Round 11),集合大小會膨脹,直接比人數必然對不上。真正該比的是
    「正規化後的收信人集合」是否一模一樣 —— 那才是會不會寄錯人的判準。

    人數一律取自 GWS 的 derive_target_audience() stats,不手算(GWS Audience Authority)。
    """
    sys.path.insert(0, str(gws / "scripts"))
    from draft_newsletter_email import derive_target_audience

    reg = json.loads((gws / "data" / "forms_registry.json").read_text(encoding="utf-8"))
    hist = list(reg["history_forms"])
    cur = reg["current_form"]["month"]
    resp = gws / "data" / "responses"

    def both_forms(stem):
        out = set()
        for r in parse_file(resp / f"{stem}_responses.jsonl", C):
            for cand in (r["verified"] or r["typed"], C.normalize_email(r["verified"] or r["typed"])):
                if cand:
                    out.add(cand.strip().lower())
        return out

    per_month = {m: both_forms(m) for m in hist}
    _, stats = derive_target_audience(
        per_month, both_forms(cur),
        load_tokens(gws / "data" / "blacklist.txt"),
        load_tokens(gws / "data" / "bounced.txt"),
        load_tokens(gws / "data" / "unsubscribed.txt"))

    gws_target, _ = derive_target_audience(
        per_month, both_forms(cur),
        load_tokens(gws / "data" / "blacklist.txt"),
        load_tokens(gws / "data" / "bounced.txt"),
        load_tokens(gws / "data" / "unsubscribed.txt"))
    gws_set = {C.normalize_email(e) for e in gws_target} - {""}

    # 本工具側:同一條鏈,但用 people 的資料模型
    hist_ids = {f"mcp-2026-{i:02d}" for i in range(1, len(hist) + 1)}
    cur_id = f"mcp-2026-{len(hist) + 1:02d}"
    mine_hist = {k for k, p in people.items() if p["eventIds"] & hist_ids}
    mine_reg = {k for k, p in people.items() if cur_id in p["eventIds"]}
    mine = {k for k in mine_hist - mine_reg if not people[k]["blocked"]}

    print("\n=== 對帳:GWS derive_target_audience() vs 本工具 ===")
    print(f"  GWS 權威 stats: history_union={stats['history_union']} "
          f"registered={stats['registered']} registered_hits={stats['registered_hits']} "
          f"blacklist_hits={stats['blacklist_hits']} bounced_hits={stats['bounced_hits']} "
          f"final={stats['final']}")
    print(f"  GWS target 正規化去重後 : {len(gws_set)} 人")
    print(f"  本工具同鏈推導          : {len(mine)} 人")
    only_gws, only_mine = gws_set - mine, mine - gws_set
    if not only_gws and not only_mine:
        print("  ✅ 兩邊收信人集合完全一致")
        return 0
    # 差異分類。已知且可接受的唯一一類:GWS 那條鏈的「correction 漏封鎖」——
    # 某人手填的位址在黑名單上,email_corrections 把它映到一個乾淨位址,
    # GWS 把兩種形式攤平進同一集合後連結就斷了,乾淨形式因而存活。
    # GWS 自己 blacklist_hit() 的 docstring 正是在警告這件事(保守方向:維持排除),
    # 本工具靠 rawEmails 保住連結,所以擋得住。這種差異是本工具較嚴,不是 bug。
    bl = load_tokens(gws / "data" / "blacklist.txt") | load_tokens(gws / "data" / "bounced.txt")
    explained, unexplained = [], []
    for e in sorted(only_gws):
        raws = people.get(e, {}).get("rawEmails", set())
        (explained if any(r in bl for r in raws) else unexplained).append(e)

    def mask(x):
        return f"{x[:3]}***@{x.split('@')[-1]}" if "@" in x else f"{x[:3]}***"

    print(f"  差異:只在 GWS {len(only_gws)} 人、只在本工具 {len(only_mine)} 人")
    for e in explained:
        print(f"     ⓘ {mask(e)} —— 手填位址在黑名單、被 correction 映到乾淨位址;"
              f"本工具維持排除(較嚴,符合 GWS blacklist_hit 的文件化意圖)")
    for e in unexplained:
        print(f"     ❌ 只在 GWS,無法解釋:{mask(e)}")
    for e in sorted(only_mine):
        print(f"     ❌ 只在本工具,無法解釋:{mask(e)}")

    if unexplained or only_mine:
        print("  ❌ 存在無法解釋的差異,視為 hard error")
        return 1
    print(f"  ✅ 收信人集合一致(本工具另多擋下 {len(explained)} 位 GWS 漏封鎖者)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只統計,不寫 Firestore")
    ap.add_argument("--gws", default=str(DEFAULT_GWS), help="GWS 專案根目錄")
    ap.add_argument("--rollback", metavar="BATCH", help="刪除某次匯入寫進去的所有文件")
    ap.add_argument("--reconcile", action="store_true",
                    help="與 GWS derive_target_audience() 對帳(不寫入)")
    args = ap.parse_args()

    if args.rollback:
        db = gnote_db.client()
        killed = 0
        for coll in ("subscribers", "events"):
            for doc in db.collection(coll).where("importBatch", "==", args.rollback).stream():
                for sub in doc.reference.collection("registrations").stream():
                    sub.reference.delete()
                doc.reference.delete()
                killed += 1
        print(f"[import_roster] 已回滾 batch {args.rollback}:刪除 {killed} 份文件")
        return 0

    gws = pathlib.Path(args.gws).expanduser()
    C = load_gws_common(gws)
    events, people, rows = build(gws, C)
    ingest_lists(people, gws, C)          # 名單軌跡 + 只在名單上的聯絡人
    tally = apply_blocks(people, gws, C)

    batch_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"\n=== 事件({len(events)}) ===")
    for eid, ev in events.items():
        print(f"  {eid:<32} {ev['category']:<10} {rows[eid]:>4} 筆  {ev['name']}")

    cats = collections.Counter(c for p in people.values() for c in p["categories"])
    blocked = sum(1 for p in people.values() if p["blocked"])
    this_month = dt.date.today().strftime("%Y-%m")
    month_people = {k for k, p in people.items() for r in p["regs"]
                    if r["category"] == "mcp" and r["eventDate"].startswith(this_month)}

    print(f"\n=== 分眾 ===")
    print(f"  MCP 歷次報名(累積)      {cats['mcp']:>4} 人")
    print(f"  MCP 當月報名({this_month})  {len(month_people):>4} 人")
    print(f"  演講資料獲得名單          {cats['slides']:>4} 人")
    print(f"  社群申請電子報名單        {cats['community']:>4} 人")
    print(f"\n=== 封鎖 ===")
    for reason, n in tally.most_common():
        print(f"  {reason:<16} {n:>4} 人")
    print(f"  ── 合計不重複            {blocked:>4} 人")
    print(f"\n=== 總計 ===")
    print(f"  訂閱者 {len(people)} 人｜報名紀錄 {sum(len(p['regs']) for p in people.values())} 筆"
          f"｜可寄送(扣除封鎖) {len(people) - blocked} 人")

    if args.reconcile:
        return reconcile(gws, C, people)

    if args.dry_run:
        print(f"\n[import_roster] dry-run,未寫入 Firestore。")
        return 0

    db = gnote_db.client()
    warn_block_divergence(db, people)
    print(f"\n[import_roster] 寫入中(batch {batch_id})…")
    write(db, events, people, batch_id, dry_run=False)
    print(f"[import_roster] 完成。回滾指令:python3 scripts/import_roster.py --rollback {batch_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
