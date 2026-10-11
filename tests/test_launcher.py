"""通过隔离的命令探测验证 macOS 入口，不打开真实浏览器或修改系统 Python。"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def command_environment(tmp_path, *, python_name=None, supported=True, launcher_exit=0):
    project = tmp_path / '中文项目 含空格'
    project.mkdir()
    entry = project / '启动系统.command'
    entry.write_bytes((ROOT / '启动系统.command').read_bytes())
    mock_bin = tmp_path / 'mock-bin'
    mock_bin.mkdir()
    log = tmp_path / 'calls.txt'
    if python_name:
        python = mock_bin / python_name
        python.write_text('#!/bin/bash\nif [ "$1" = "-c" ]; then\n'
                          + f'  exit {0 if supported else 1}\nfi\n'
                          + 'printf "%s\\n" "$PWD" "$@" >> "$LAUNCH_LOG"\n'
                          + f'exit {launcher_exit}\n')
        python.chmod(0o755)
    browser = mock_bin / 'open'
    browser.write_text('#!/bin/bash\nprintf "browser:%s\\n" "$1" >> "$LAUNCH_LOG"\n')
    browser.chmod(0o755)
    # 只模拟 Python / open 的发现；防止测试机上已安装的 Python 干扰缺失环境用例。
    bash_env = tmp_path / 'shell-env'
    bash_env.write_text('''command() {
    if [ "$1" = "-v" ]; then
        case "$2" in
            python3.12|python3|open)
                if [ -x "$MOCK_BIN/$2" ]; then printf '%s\\n' "$MOCK_BIN/$2"; return 0; fi
                return 1;;
            *) return 1;;
        esac
    fi
    builtin command "$@"
}
''')
    env = dict(os.environ, BASH_ENV=str(bash_env), MOCK_BIN=str(mock_bin), LAUNCH_LOG=str(log),
               PATH=str(mock_bin) + os.pathsep + os.environ.get('PATH', ''))
    result = subprocess.run(['bash', str(entry)], input='\n', text=True, capture_output=True, env=env, timeout=10)
    return result, log.read_text() if log.exists() else '', project


@pytest.mark.parametrize('python_name', ['python3.12', 'python3'])
def test_mac_detects_python_and_handles_chinese_space_path(tmp_path, python_name):
    result, log, project = command_environment(tmp_path, python_name=python_name)
    assert result.returncode == 0
    assert str(project) in log
    assert 'scripts/local_launcher.py' in log
    assert 'browser:' not in log
    assert '已找到 Python 3.12' in result.stdout


@pytest.mark.parametrize('python_name', [None, 'python3'])
def test_mac_missing_or_old_python_opens_official_install_page(tmp_path, python_name):
    result, log, _ = command_environment(tmp_path, python_name=python_name, supported=False)
    assert result.returncode == 1
    assert 'macOS 64-bit universal2 installer' in result.stdout
    assert 'browser:https://www.python.org/downloads/release/python-31210/' in log
    assert 'scripts/local_launcher.py' not in log


def test_mac_preserves_launcher_failure_exit_status(tmp_path):
    result, _, _ = command_environment(tmp_path, python_name='python3.12', launcher_exit=7)
    assert result.returncode == 7
    assert '启动未完成' in result.stdout
