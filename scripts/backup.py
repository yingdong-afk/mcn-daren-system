"""使用 SQLite 在线备份，避免仅复制活跃的 WAL 主文件而丢失数据。"""
import argparse
import os
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description='备份达人数据库（不会包含登录会话密钥）')
parser.add_argument('output', help='新的备份文件路径，不允许覆盖已有文件')
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
source = Path(os.environ.get('MCN_INSTANCE_DIR', str(root / 'instance'))) / 'mcn.sqlite3'
if not source.exists():
    parser.error('数据库尚不存在，请先初始化应用')
target = Path(args.output).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
try:
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    parser.error('目标文件已存在，请换一个文件名')
else:
    os.close(fd)
try:
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('备份完整性检查失败')
except Exception:
    target.unlink(missing_ok=True)
    raise
print('数据库备份完成：', target)
