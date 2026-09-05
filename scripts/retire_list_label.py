#!/usr/bin/env python3
"""把一個已退役的名單軌跡標籤從 subscribers.lists[] 移除。

用途:某次任務的臨時名單(例:「永久收件人」)事後確認不是長期分眾,要讓它
從後台的分眾清單消失。因為分眾是從資料即時枚舉出來的(admin.jsx buildSegments),
**唯一讓它消失的方法就是把標籤從資料裡拿掉**——在前端加一份「不要顯示」的
黑名單只會讓程式又長回硬編清單,下一個退役標籤照樣漏掉。

只動 lists[] 一個欄位:不刪聯絡人、不碰 eventIds/blocked/name/tags。
執行前務必先 --dry-run,它會印出受影響的人以及「拿掉之後還剩什麼軌跡」。
移除的名單會存成 JSON,要復原就用 --restore <檔案>。

  python3 scripts/retire_list_label.py "永久收件人" --dry-run
  python3 scripts/retire_list_label.py "永久收件人" --apply
  python3 scripts/retire_list_label.py --restore .secrets/retired_xxx.json

注意:標籤若還留在 import_roster.py 的 LIST_SOURCES,下次匯入會整批貼回來。
退役一個標籤 = 這支腳本清資料 + LIST_SOURCES 拿掉那一行,兩件事都要做。
"""
import argparse, json, os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnote_db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, ".secrets")   # gitignored:內含 email,不進版控


def collect(db, label):
    hits = []
    for d in db.collection("subscribers").stream():
        x = d.to_dict() or {}
        if label in (x.get("lists") or []):
            hits.append((d.id, list(x.get("lists") or [])))
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", nargs="?", help="要退役的標籤,例如「永久收件人」")
    ap.add_argument("--dry-run", action="store_true", help="只印出受影響的人,不寫入")
    ap.add_argument("--apply", action="store_true", help="實際寫入")
    ap.add_argument("--restore", metavar="JSON", help="用先前產生的備份把標籤加回去")
    a = ap.parse_args()

    db = gnote_db.client()
    fs = __import__("google.cloud.firestore", fromlist=["firestore"])

    if a.restore:
        rec = json.load(open(a.restore, encoding="utf-8"))
        label, ids = rec["label"], [k for k, _ in rec["subscribers"]]
        print(f'復原標籤「{label}」到 {len(ids)} 位聯絡人')
        batch, n = db.batch(), 0
        for k in ids:
            batch.set(db.collection("subscribers").document(k),
                      {"lists": fs.ArrayUnion([label])}, merge=True)
            n += 1
            if n % 400 == 0:
                gnote_db.commit(batch); batch = db.batch()
        gnote_db.commit(batch)
        print("完成")
        return

    if not a.label:
        ap.error("需要指定標籤(或用 --restore)")
    if not (a.dry_run or a.apply):
        ap.error("請明確指定 --dry-run 或 --apply")

    hits = collect(db, a.label)
    print(f'標籤「{a.label}」:{len(hits)} 位聯絡人\n')
    for i, (k, lists) in enumerate(hits, 1):
        rest = [l for l in lists if l != a.label]
        print(f'{i:>3}. …@{k.split("@")[-1]}')
        print(f'     拿掉後剩下的軌跡:{rest or "(沒有其他軌跡,但聯絡人本身仍在)"}')

    if not hits:
        print("沒有人帶這個標籤,不需要處理。")
        return
    if a.dry_run:
        print("\n(dry-run,未寫入)")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(OUT_DIR, f"retired_{stamp}.json")
    json.dump({"label": a.label, "retiredAt": stamp, "subscribers": hits},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n備份(含 email,已 gitignore):{path}")

    batch, n = db.batch(), 0
    for k, _ in hits:
        batch.set(db.collection("subscribers").document(k),
                  {"lists": fs.ArrayRemove([a.label])}, merge=True)
        n += 1
        if n % 400 == 0:
            gnote_db.commit(batch); batch = db.batch()
    gnote_db.commit(batch)
    print(f"已從 {n} 位聯絡人移除標籤「{a.label}」。聯絡人本身一個都沒有刪。")
    print("記得同步把 LIST_SOURCES 裡對應那一行拿掉,否則下次匯入會貼回來。")


if __name__ == "__main__":
    main()
