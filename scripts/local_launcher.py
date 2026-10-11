"""本机启动向导；只有在用户电脑执行时才打开其本机浏览器。"""
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run():
    os.chdir(ROOT)
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('正在准备运行环境，请稍候……', flush=True)
        venv.create(ROOT / '.venv', with_pip=True)
    print('正在检查并安装依赖，首次启动需要联网……', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
    # 子进程初始化数据库，确保使用虚拟环境中安装的依赖。
    subprocess.run([str(python), '-c', 'from app import create_app; create_app()'], check=True)
    instance = Path(os.environ.get('MCN_INSTANCE_DIR', str(ROOT / 'instance')))
    with sqlite3.connect(instance / 'mcn.sqlite3') as conn:
        has_users = conn.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0] > 0
    if not has_users:
        print('首次使用：请设置管理员密码（至少10位，输入时不显示）。账号为 admin。', flush=True)
        subprocess.run([str(python), '-m', 'flask', '--app', 'app:create_app', 'init-admin'], check=True)
    port = int(os.environ.get('MCN_PORT', '8080'))
    if not 1 <= port <= 65535:
        raise RuntimeError('端口必须在1至65535之间。')
    address = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([str(python), '-m', 'waitress', '--host=127.0.0.1', f'--port={port}', '--call', 'app:create_app'])
    try:
        # 禁用网络代理，仅查询本机启动的服务。
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError(f'服务启动失败；请检查{port}端口是否已被占用，并查看上面的提示。')
            try:
                with http.open(address + '/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.25)
        else:
            raise RuntimeError('服务未能及时启动，请查看上面的提示。')
        print('系统已启动，正在打开浏览器。请保持此窗口打开；按 Ctrl+C 可停止。', flush=True)
        webbrowser.open(address)
        if process.wait() != 0:
            raise RuntimeError('服务已退出，请查看上面的提示。')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print('\n系统已停止，数据已保留。')
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('启动失败：', error, file=sys.stderr)
        sys.exit(1)
