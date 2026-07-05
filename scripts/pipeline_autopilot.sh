#!/bin/bash
# pipeline_autopilot.sh — 閉環入口(薄殼):音檔(+圖片)→ Step1→2(B/C/D)→圖片理解→插圖
# → S4.5 gate → 印上架摘要後停。deploy 由使用者說「發」(原則:對外發布保留人工扳機)。
#
# 用法:
#   scripts/pipeline_autopilot.sh <audio> [--images <dir>] [--context "..."] [--domain d]
#
# 分工(CLAUDE.md 原則 5/6/9):
#   - 本腳本只跑「確定性」步驟(session.py 建容器/轉錄/Phase A + marker 鏈生成)。
#   - 「判斷」步驟(Phase B/C/D 校稿、圖片描述後驗、Haiku anchors)由對話 agent
#     依 marker 鏈順序接手:phase-b → phase-c → phase-d → images → image-insert。
#   - agent 全部清完後,跑 prepublish_gate;綠 → 印上架摘要,等使用者「發」。
set -euo pipefail
AUDIO="$1"; shift
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "═══ 閉環管線啟動(自動到出版前;deploy 人工)═══"
python3 "$ROOT/scripts/session.py" new "$AUDIO" --stop-at image-insert "$@"

# 找出剛建立的 session(session.py 依日期+檔名 slug)
SLUG_DIR=$(ls -td "$ROOT"/sessions/*/ | head -1)
echo
echo "═══ marker 鏈狀態(對話 agent 依序接手,清一個驗一個)═══"
for m in .phase_b_pending.json .phase_c_pending.json .phase_d_pending.json \
         .images_pending.json .image_insert_pending.json; do
  if [ -f "$SLUG_DIR/$m" ]; then echo "  ☐ $m"; else echo "  ✓ $m(不需要/已完成)"; fi
done
cat <<EOF

═══ 對話 agent 待辦順序 ═══
 1. Phase B 校稿 cleaned.md(§ R2,零省略、字數門)
 2. Phase C 標點(normalize_punctuation.py + § R7.2 冒號)
 3. Phase D hook(§ R8,段落數 1:1)
 4. python3 scripts/describe_images.py --session <session>(圖片理解,自動清 marker)
 5. insert_images.py --plan → Haiku subagent anchors → --apply → --verify
 6. python3 scripts/prepublish_gate.py <session>/cleaned.md(gate 綠才算完)
 7. 印上架摘要(slug/書架/字數/圖數)→ 停,等使用者說「發」
 8. 使用者確認後:publish_goodedunote.sh + publish_qaqc.py(品質迴圈,fail 修一輪重驗,上限 2)
EOF
echo "session: $SLUG_DIR"
