#!/usr/bin/env python3
"""為某本 goodedunote 書的 session 頁加上「前端密碼軟鎖」(校稿期間用)。

注意:這是 client-side gate,內容仍在原始碼裡,擋的是隨手點閱,不是真安全。
校稿完要「全開放」→ 直接重跑 publish_goodedunote.sh 重生頁面即可(新頁不含鎖),
或跑本腳本 --unlock 拆掉鎖再 deploy。

用法:
  鎖:  python3 scripts/lock_sessions.py <slug> <password>
  解:  python3 scripts/lock_sessions.py <slug> --unlock
作用對象:scripts/publish/goodedunote/public/<slug>/session-*.html
(改完記得 deploy:cd scripts/publish/goodedunote && firebase deploy --only hosting --project goodedunote --account codefortaiwan.com@gmail.com)
"""
import sys, re, pathlib, glob

ROOT = pathlib.Path("/Users/shuotaochiang/Desktop/study")
MARK_A, MARK_B = "<!--LOCK-GATE-->", "<!--/LOCK-GATE-->"

def gate_html(slug, pw):
    return f'''{MARK_A}
<div id="__lock" style="position:fixed;inset:0;z-index:99999;background:#f5f1ea;display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,sans-serif;">
  <div style="text-align:center;max-width:340px;padding:24px;">
    <p style="color:#9a8678;font-size:15px;margin-bottom:6px;letter-spacing:.04em;">校稿中 · 暫不公開</p>
    <p style="color:#b8a99c;font-size:13px;margin-bottom:18px;">請輸入密碼閱讀</p>
    <input id="__pw" type="password" inputmode="numeric" autocomplete="off" autofocus
      style="font-size:18px;padding:10px 14px;border:1px solid #d4c0b3;border-radius:8px;width:160px;text-align:center;outline:none;">
    <button id="__go" style="display:block;margin:14px auto 0;font-size:14px;padding:8px 22px;border:1px solid #d4c0b3;border-radius:8px;background:#fff;color:#9a8678;cursor:pointer;">進入</button>
    <p id="__err" style="color:#c0392b;font-size:13px;height:18px;margin-top:10px;"></p>
  </div>
</div>
<script>
(function(){{
  var KEY='gd_unlock_{slug}', PW='{pw}';
  var html=document.documentElement;
  function unlock(){{var l=document.getElementById('__lock');if(l)l.remove();html.style.overflow='';}}
  if(sessionStorage.getItem(KEY)==='1'){{unlock();return;}}
  html.style.overflow='hidden';
  function go(){{
    var i=document.getElementById('__pw');if(!i)return;
    if(i.value.trim()===PW){{sessionStorage.setItem(KEY,'1');unlock();}}
    else{{document.getElementById('__err').textContent='密碼不對';i.select();}}
  }}
  document.addEventListener('click',function(e){{if(e.target&&e.target.id==='__go')go();}});
  document.addEventListener('keydown',function(e){{if(e.key==='Enter'&&document.getElementById('__pw'))go();}});
}})();
</script>
{MARK_B}
'''

def strip(text):
    return re.sub(re.escape(MARK_A)+r".*?"+re.escape(MARK_B)+r"\n?", "", text, flags=re.S)

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    slug = sys.argv[1]; arg = sys.argv[2]
    pub = ROOT/"scripts"/"publish"/"goodedunote"/"public"/slug
    files = sorted(glob.glob(str(pub/"session-*.html")))
    if not files:
        sys.exit(f"找不到 session 頁:{pub}/session-*.html")
    unlock = (arg == "--unlock")
    for f in files:
        p = pathlib.Path(f); t = p.read_text(encoding="utf-8")
        t = strip(t)  # 先移除既有鎖(idempotent)
        if not unlock:
            t = t.replace("<body>", "<body>\n"+gate_html(slug, arg), 1)
        p.write_text(t, encoding="utf-8")
        print(f"  {'unlocked' if unlock else 'locked  '} {p.name}")
    print(f"{'已解鎖' if unlock else '已上鎖(密碼='+arg+')'} {len(files)} 頁。記得 deploy。")

if __name__ == "__main__":
    main()
