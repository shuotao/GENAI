#!/usr/bin/env python3
"""把 GA4 的文章瀏覽數同步進 Firestore,供後台 /admin/ 顯示。

為什麼是「本機指令」而不是 Cloud Function:
    GA4 Data API 需要 service account 金鑰。靜態頁沒辦法安全地持有金鑰,
    而 Cloud Functions 需要把 goodedunote 升級到 Blaze 方案。在本機跑一行指令
    最省事,金鑰也不必離開這台電腦。代價是數字不會自己更新 —— 想看新數字就重跑。

前置(各做一次):
    1. GA4 →「管理」→「資源存取管理」→ 新增
       goodedunote-admin-cli@goodedunote.iam.gserviceaccount.com 為「檢視者」
    2. python3 scripts/sync_ga_stats.py --discover   ← 取得 property ID
    3. 把 GA4_PROPERTY_ID=<數字> 寫進專案根的 .env

用法:
    python3 scripts/sync_ga_stats.py --discover
    python3 scripts/sync_ga_stats.py --dry-run --days 7
    python3 scripts/sync_ga_stats.py --days 30
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gnote_db  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA_JS = REPO / "scripts" / "publish" / "goodedunote" / "public" / "data.js"
ENV = REPO / ".env"


def env(key: str) -> str:
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    return os.environ.get(key, "")


def known_books() -> dict:
    """合法 slug 清單直接取自 data.js —— 那是書架的 SSoT,不另外維護一份。

    刻意用正規表示式而非 JS 解析器:data.js 是手寫的字面量陣列,
    只需要 id/title/shelf 三個欄位,不值得為此引入 node 依賴。
    """
    if not DATA_JS.exists():
        sys.exit(f"[sync_ga_stats] 找不到 {DATA_JS}")
    src = DATA_JS.read_text(encoding="utf-8")
    books = {}
    shelves = list(re.finditer(r"id:\s*'(public|seminar|reading)'", src))
    for i, sm in enumerate(shelves):
        start = sm.end()
        end = shelves[i + 1].start() if i + 1 < len(shelves) else len(src)
        for bm in re.finditer(
                r"id:\s*'([^']+)',\s*\n\s*title:\s*'((?:[^'\\]|\\.)*)'", src[start:end]):
            books[bm.group(1)] = {"title": bm.group(2).replace("\\'", "'"),
                                  "shelf": sm.group(1)}
    return books


def discover(creds_path: pathlib.Path) -> int:
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    client = AnalyticsAdminServiceClient()
    found = False
    for acc in client.list_account_summaries():
        print(f"帳戶:{acc.display_name}")
        for p in acc.property_summaries:
            print(f"   GA4_PROPERTY_ID={p.property.split('/')[-1]}   {p.display_name}")
            found = True
    if not found:
        print("找不到任何 GA4 資源。請先在 GA4 →「管理」→「資源存取管理」把\n"
              "  goodedunote-admin-cli@goodedunote.iam.gserviceaccount.com\n"
              "  加為「檢視者」,再重跑本指令。", file=sys.stderr)
        return 1
    print("\n把上面那行 GA4_PROPERTY_ID=… 貼進專案根的 .env 即可。")
    return 0


def fetch(property_id: str, days: int):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest)
    client = BetaAnalyticsDataClient()
    return client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        dimensions=[Dimension(name="pagePath"), Dimension(name="date")],
        metrics=[Metric(name="screenPageViews"), Metric(name="totalUsers")],
        limit=100000))


def slug_of(path: str, books: dict):
    """/bim-mcp-8/session-3.html → bim-mcp-8。非書本路徑(首頁、admin)回 None。"""
    parts = [p for p in path.split("?")[0].split("/") if p]
    return parts[0] if parts and parts[0] in books else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--discover", action="store_true",
                    help="列出這個 service account 看得到的 GA4 property ID")
    args = ap.parse_args()

    if args.discover:
        return discover(gnote_db.KEY)

    pid = env("GA4_PROPERTY_ID")
    if not pid:
        sys.exit("[sync_ga_stats] .env 缺 GA4_PROPERTY_ID。\n"
                 "  先跑:python3 scripts/sync_ga_stats.py --discover")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(gnote_db.KEY)
    books = known_books()
    print(f"[sync_ga_stats] data.js 認得 {len(books)} 本書;拉取最近 {args.days} 天…")
    resp = fetch(pid, args.days)

    agg = collections.defaultdict(
        lambda: {"views": 0, "users": 0, "pages": collections.Counter(),
                 "daily": collections.Counter()})
    skipped = 0
    for row in resp.rows:
        path, date = row.dimension_values[0].value, row.dimension_values[1].value
        views = int(row.metric_values[0].value or 0)
        users = int(row.metric_values[1].value or 0)
        slug = slug_of(path, books)
        if not slug:
            skipped += views
            continue
        a = agg[slug]
        a["views"] += views
        a["users"] += users      # 註:逐日 totalUsers 相加會高估不重複人數,僅供相對比較
        a["pages"][path] += views
        a["daily"][date] += views

    print(f"  命中 {len(agg)} 本書｜非書本路徑(首頁等)瀏覽 {skipped} 次不計入\n")
    rows = sorted(agg.items(), key=lambda kv: -kv[1]["views"])
    for slug, a in rows:
        print(f"  {a['views']:>7}  {a['users']:>6}  {slug:<32} {books[slug]['title'][:28]}")
    print(f"  {'-'*7}  {'-'*6}")
    print(f"  {sum(a['views'] for _, a in rows):>7}  總計")

    if args.dry_run:
        print("\n[sync_ga_stats] dry-run,未寫入 Firestore。")
        return 0

    db = gnote_db.client()
    batch = db.batch()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for slug, a in rows:
        batch.set(db.collection("stats").document(slug), {
            "title": books[slug]["title"], "shelf": books[slug]["shelf"],
            "totalViews": a["views"], "totalUsers": a["users"],
            "pages": [{"path": p, "views": v} for p, v in a["pages"].most_common()],
            "daily": [{"date": d, "views": v} for d, v in sorted(a["daily"].items())],
            "windowDays": args.days, "syncedAt": now,
        }, merge=True)
    gnote_db.commit(batch)
    print(f"\n[sync_ga_stats] 已寫入 {len(rows)} 筆到 Firestore stats/(syncedAt={now})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
