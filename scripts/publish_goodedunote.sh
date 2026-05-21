#!/bin/bash
# Step 5(出版層)— 把一篇筆記的 cleaned.md(+toc.json)轉成「多頁式」HTML
# (index + 每場一頁,各自 OG 預覽圖),圖片壓縮後 deploy 到 Firebase goodedunote。
#
# 邊界(CLAUDE.md 原則 7):只動 goodedunote 的 hosting,不碰 GENAI /web、不碰其他專案/規則。
#
# 用法:
#   scripts/publish_goodedunote.sh <cleaned.md> <workdir(含 toc.json)> <slug> [圖片來源目錄] [md_to_html 額外參數…]
# 範例(Koshi Cafe,含封面):
#   scripts/publish_goodedunote.sh \
#     "ClaudeDesign/Koshi Cafe 完整逐字稿.cleaned.md" "ClaudeDesign/_kc_build" koshi-cafe "ClaudeDesign" \
#     --cover IMG_1585.JPG --tagline "Claude Code for Artists · Taipei"
set -euo pipefail
MD="$1"; WD="$2"; SLUG="$3"; IMGSRC="${4:-$(dirname "$MD")}"; shift 4 || true
EXTRA=("$@")

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/scripts/publish/goodedunote"
PUB="$DEPLOY/public/$SLUG"
BASE="https://goodedunote.web.app/$SLUG/"
mkdir -p "$PUB"

[ -f "$DEPLOY/firebase.json" ] || cat > "$DEPLOY/firebase.json" <<'JSON'
{ "hosting": { "public": "public", "ignore": ["firebase.json", "**/.*"] } }
JSON
[ -f "$DEPLOY/.firebaserc" ] || echo '{ "projects": { "default": "goodedunote" } }' > "$DEPLOY/.firebaserc"

# 清掉舊頁(避免章節數變動留下殘頁),保留/覆寫圖片
rm -f "$PUB"/index.html "$PUB"/session-*.html

# 1) md → 多頁 HTML(每頁自帶 OG;封面/base-url 由參數帶入)
python3 "$ROOT/scripts/lang/en/md_to_html.py" "$MD" "$WD" "$PUB" --multipage --base-url "$BASE" "${EXTRA[@]}"

# 2) 蒐集所有頁面參照到的本地圖檔 → 壓縮 + EXIF 轉正後放進部署夾(省流量、自動轉正)
SRCS=()
while IFS= read -r r; do
  [ -z "$r" ] && continue
  case "$r" in http://*|https://*) continue;; esac
  [ -f "$IMGSRC/$r" ] && SRCS+=("$IMGSRC/$r")
done < <(grep -hoE 'src="[^"]+"' "$PUB"/*.html | sed 's/^src="//;s/"$//' | sort -u)
if [ "${#SRCS[@]}" -gt 0 ]; then
  echo "[publish] 壓縮 ${#SRCS[@]} 張圖 → $PUB"
  python3 "$ROOT/scripts/compress_images.py" "$PUB" "${SRCS[@]}"
fi

# 3) 部署(只 hosting,只 goodedunote)
( cd "$DEPLOY" && firebase deploy --only hosting --project goodedunote )
echo "✅ Step 5 已上線: $BASE"
