#!/bin/bash
# macOS Finder 双击入口；不使用系统自带的旧版 Python。
set -u
set -o pipefail
cd "$(dirname "$0")" || exit 1

python_bin=""
for candidate in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    # macOS 的 /usr/bin/python3 可能是触发 Xcode 安装的占位程序。
    if [ "$resolved" = "/usr/bin/python3" ]; then
        continue
    fi
    if [ -n "$resolved" ] && "$resolved" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
        python_bin="$resolved"
        break
    fi
done

if [ -z "$python_bin" ]; then
    echo "没有找到 Python 3.12。macOS 自带的旧版 Python 不适用于本项目。"
    echo "请在打开的官方页面选择 macOS 64-bit universal2 installer，安装完成后再次双击本文件。"
    echo "该安装包支持 Apple 芯片和 Intel MacBook，无需安装 Homebrew。"
    if command -v open >/dev/null 2>&1; then
        open "https://www.python.org/downloads/release/python-31210/" || true
    fi
    read -r -p "按回车键关闭窗口……" || true
    exit 1
fi

echo "已找到 Python 3.12，正在启动 MCN 达人商务管理系统……"
"$python_bin" scripts/local_launcher.py
result=$?
if [ "$result" -ne 0 ]; then
    echo "启动未完成，请保留上面的错误提示。"
fi
read -r -p "按回车键关闭窗口……" || true
exit "$result"
