#!/usr/bin/env python3
"""goodedunote 後台的共用 Firestore 連線層。

由 seed_admin.py / import_roster.py / sync_ga_stats.py 共用,避免三份重複的
憑證載入與重試邏輯。

為什麼需要 retry:新建的 service account IAM 綁定在 Firestore 各前端之間是
最終一致的,剛授權後數分鐘內會間歇性回 403 PermissionDenied(實測 5 次中 1 次)。
這不是設定錯誤,重試即可通過;但沒有重試的批次寫入會在中途炸掉、留下半套資料。
"""
import functools
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
KEY = REPO / ".secrets" / "goodedunote-admin-cli.json"
PROJECT = "goodedunote"


def client():
    """回傳已認證的 Firestore client(server SDK,繞過 firestore.rules)。"""
    if not KEY.exists():
        sys.exit(
            f"[gnote_db] 找不到 service account 金鑰:{KEY}\n"
            f"  重建方式:\n"
            f"    gcloud iam service-accounts keys create {KEY} \\\n"
            f"      --iam-account=goodedunote-admin-cli@goodedunote.iam.gserviceaccount.com \\\n"
            f"      --project=goodedunote --account=codefortaiwan.com@gmail.com\n"
            f"  金鑰在 .gitignore 內,絕不進 git。"
        )
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(KEY)
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)


def retry(fn=None, *, tries=6, base=2.0):
    """對 PermissionDenied / ServiceUnavailable 做指數退避重試。

    只重試這兩種「會自己好」的錯誤;其他例外直接往上拋,不掩蓋真正的 bug。
    """
    if fn is None:
        return functools.partial(retry, tries=tries, base=base)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from google.api_core import exceptions as gexc
        transient = (gexc.PermissionDenied, gexc.ServiceUnavailable,
                     gexc.DeadlineExceeded, gexc.Aborted)
        for attempt in range(1, tries + 1):
            try:
                return fn(*args, **kwargs)
            except transient as exc:
                if attempt == tries:
                    raise
                wait = base * (2 ** (attempt - 1))
                print(f"    [retry {attempt}/{tries}] {type(exc).__name__},{wait:.0f}s 後重試",
                      file=sys.stderr)
                time.sleep(wait)
    return wrapper


@retry
def commit(batch):
    """送出一個 WriteBatch(帶重試)。"""
    return batch.commit()
