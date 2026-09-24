#!/usr/bin/env bash
# smoke.sh —— 工作台冒烟测试:服务/全部只读 API/静态资源/JS 语法/模块导入
# 用法: bash scripts/smoke.sh [port]   (默认 8620)
set -uo pipefail
PORT="${1:-8620}"
B="http://127.0.0.1:$PORT"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }

echo "== 1. 服务与只读 API =="
for ep in /api/health /api/overview /api/projects /api/pool /api/audition /api/jobs /api/config; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$B$ep")
  [ "$code" = "200" ] && ok "$ep" || bad "$ep → $code"
done

echo "== 2. 首页与静态资源 =="
for p in / /static/css/app.css /static/js/main.js; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$B$p")
  [ "$code" = "200" ] && ok "$p" || bad "$p → $code"
done
curl -sI -m 5 "$B/static/js/ui.js" | grep -qi 'cache-control: no-store' && ok "静态资源 no-store" || bad "静态资源缺 no-store"

echo "== 3. 项目详情(每个存量项目) =="
for name in $(curl -s -m 10 "$B/api/projects" | python3 -c "import json,sys;print(' '.join(json.load(sys.stdin)['projects']))"); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$B/api/projects/$name")
  [ "$code" = "200" ] && ok "detail $name" || bad "detail $name → $code"
done

echo "== 4. 媒体网关 =="
code=$(curl -s -o /dev/null -w '%{http_code}' "$B/api/media?path=/etc/passwd")
[ "$code" = "403" ] && ok "白名单拦截(403)" || bad "越权路径 → $code"
ANY_PNG=$(find "$HOME/桌面/AI角色工坊/素材" -name '01_正面特写.png' 2>/dev/null | head -1)
if [ -n "$ANY_PNG" ]; then
  ENC=$(python3 -c "from urllib.parse import quote;print(quote('$ANY_PNG'))")
  code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' "$B/api/media?path=$ENC")
  [ "$code" = "206" ] && ok "Range 206" || bad "Range → $code"
else
  echo "  (无演员图可测 Range,跳过)"
fi

echo "== 5. 前端 JS 语法 =="
if command -v node >/dev/null; then
  JS_FAIL=0
  for f in "$ROOT"/sdapi/static/js/**/*.js "$ROOT"/sdapi/static/js/*.js; do
    [ -f "$f" ] || continue
    node --check "$f" 2>/dev/null || { JS_FAIL=1; bad "语法 $f"; }
  done
  [ $JS_FAIL -eq 0 ] && ok "全部 JS 语法通过" || true
else
  echo "  (无 node,跳过)"
fi

echo "== 6. 后端模块导入 =="
PY="${HOME}/venvs/sdapi/bin/python"
[ -x "$PY" ] || PY=python3
( cd "$ROOT" && "$PY" -c "
import sys; sys.path.insert(0, '.')
import sd.audition, sd.qwenimage, sdapi.server
print('  ✓ sd + sdapi 导入 OK')" ) || bad "模块导入失败"

echo
echo "结果: $PASS 通过, $FAIL 失败"
[ $FAIL -eq 0 ]
