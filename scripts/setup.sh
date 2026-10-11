#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
echo '依赖安装完成。首次使用：.venv/bin/flask --app app:create_app init-admin'
echo '启动应用：bash scripts/start.sh'
