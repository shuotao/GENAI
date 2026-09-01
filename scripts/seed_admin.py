#!/usr/bin/env python3
"""種下 goodedunote 後台的兩份基礎字典:管理員白名單與封鎖理由。

為什麼要有這支:firestore.rules 刻意讓 admins/ 的 write 永遠為 false ——
前端若能寫 admins/,任何登入者都能把自己加進白名單、自我提權。
所以白名單只能由本機、拿 service account 金鑰(繞過規則)寫入。

用法:
    python3 scripts/seed_admin.py --dry-run
    python3 scripts/seed_admin.py
    python3 scripts/seed_admin.py --add someone@example.com
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gnote_db  # noqa: E402  ← 共用連線層(憑證 + 重試)

# 後台管理員。改這裡再重跑即可(冪等)。
ADMINS = [
    "codefortaiwan.com@gmail.com",   # Firebase 專案擁有者 / 部署帳號
    "shuotao.as@gmail.com",          # Forms / 日常使用帳號
]

# 內建封鎖理由。builtin=True 的不給後台刪,避免既有資料指向不存在的理由。
BLOCK_REASONS = [
    ("email-invalid", "EMAIL 錯誤"),
    ("refused",       "拒收戶"),
    ("unsubscribed",  "退訂"),
    ("bounced",       "退信 (bounce)"),
    ("duplicate",     "重複"),
    ("not-target",    "非目標對象"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--add", action="append", default=[], metavar="EMAIL",
                    help="除了內建清單外,額外加入的管理員 email(可重複)")
    args = ap.parse_args()

    from google.cloud import firestore as fs
    db = gnote_db.client()
    admins = ADMINS + [e.strip().lower() for e in args.add]

    batch = db.batch()
    for email in admins:
        print(f"  admin  {email}")
        batch.set(db.collection("admins").document(email),
                  {"addedAt": fs.SERVER_TIMESTAMP}, merge=True)

    for rid, label in BLOCK_REASONS:
        print(f"  reason {rid:<14} {label}")
        batch.set(db.collection("blockReasons").document(rid),
                  {"label": label, "builtin": True}, merge=True)

    if not args.dry_run:
        gnote_db.commit(batch)

    verb = "會寫入" if args.dry_run else "已寫入"
    print(f"[seed_admin] {verb} {len(admins)} 位管理員、{len(BLOCK_REASONS)} 個封鎖理由")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
