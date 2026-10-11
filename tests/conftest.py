import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from app import create_app, now


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'only-for-isolated-tests', 'DATABASE': str(tmp_path / 'test.sqlite3')})
    with sqlite3.connect(app.config['DATABASE']) as conn:
        for username, role in [('admin', 'admin'), ('staff', 'staff'), ('other', 'staff')]:
            conn.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                         (username, '测试员工-' + username, generate_password_hash('TestPassword123!'), role, now()))
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def post(client, path, data=None, **kwargs):
    client.get('/login')
    with client.session_transaction() as session:
        csrf = session['csrf']
    if 'json' in kwargs:
        kwargs['headers'] = {'X-CSRF-Token': csrf}
        return client.post(path, **kwargs)
    return client.post(path, data={**(data or {}), 'csrf_token': csrf}, **kwargs)


def login(client, username='admin'):
    return post(client, '/login', {'username': username, 'password': 'TestPassword123!'})


def create_talent(client, **overrides):
    # 合成数据仅用于 pytest 临时数据库，不会写入实际运行的数据库。
    data = dict(nickname='测试专用达人', douyin_id='test_only_01', fans='10000', categories='测试类目',
                content_types='测试内容', historical_gmv='1000.00', sales_period='测试周期', data_source='单元测试合成数据', owner_id='2')
    data.update(overrides)
    return post(client, '/talents/new', data)
