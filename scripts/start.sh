#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/waitress-serve ]]; then
    echo '请先运行 bash scripts/setup.sh 安装依赖。' >&2
    exit 1
fi
exec .venv/bin/waitress-serve --host="${MCN_HOST:-127.0.0.1}" --port="${MCN_PORT:-8080}" --threads=4 --call app:create_app
