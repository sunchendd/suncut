#!/usr/bin/env bash
# 启动短剧工作台(sdapi):默认 http://127.0.0.1:8620
# 局域网访问: SDAPI_HOST=0.0.0.0 ./sdapi-serve.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/venvs/sdapi/bin/python"
[ -x "$PY" ] || { echo "缺 venv: 先 python3 -m venv ~/venvs/sdapi && ~/venvs/sdapi/bin/pip install fastapi 'uvicorn[standard]'"; exit 1; }
exec "$PY" -m uvicorn sdapi.server:app \
  --host "${SDAPI_HOST:-127.0.0.1}" --port "${SDAPI_PORT:-8620}" --workers 1
