import io
import sqlite3

from openpyxl import Workbook

from conftest import create_talent, login, post


def rows(app, query):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        return conn.execute(query).fetchall()


def test_empty_database_and_authentication(app, client):
    assert client.get('/health').json == {'status': 'ok', 'database': 'ok'}
    assert client.get('/talents').status_code == 302
    assert client.get('/api/v1/talents').status_code == 401
    assert rows(app, 'SELECT COUNT(*) FROM talents') == [(0,)]
    assert login(client).status_code == 302
    assert '还没有达人档案' in client.get('/').text
    for path in ['/talents', '/talents/new', '/screening', '/import', '/users', '/account']:
        assert client.get(path).status_code == 200


def test_create_edit_search_and_persistence(app, client):
    login(client)
    assert create_talent(client).status_code == 302
    assert '测试专用达人' in client.get('/talents?q=test_only').text
    assert '测试专用达人' not in client.get('/talents?category=不存在的类目').text
    assert rows(app, 'SELECT fans,historical_gmv_cents,status FROM talents') == [(10000, 100000, '待联系')]
    assert create_talent(client, nickname='测试重复', douyin_id='TEST_ONLY_01').status_code == 200
    assert rows(app, 'SELECT COUNT(*) FROM talents') == [(1,)]
    result = post(client, '/talents/1/edit', dict(nickname='测试修改', douyin_id='test_only_01', fans='', historical_gmv='', categories='', content_types='', owner_id='2'))
    assert result.status_code == 302
    assert rows(app, 'SELECT nickname,fans,historical_gmv_cents FROM talents') == [('测试修改', None, None)]
    assert client.get('/talents/1').status_code == 200


def test_permission_csrf_and_status_audit(app, client):
    login(client)
    create_talent(client)
    assert client.post('/talents/1/status', data={'status': '已成交', 'notes': '无CSRF'}).status_code == 400
    assert client.post('/talents/1/status', data={'csrf_token': '非ASCII令牌', 'status': '已成交', 'notes': '非法CSRF'}).status_code == 400
    login(client, 'other')
    assert client.get('/users').status_code == 403
    assert client.get('/talents/1/edit').status_code == 403
    assert post(client, '/talents/1/status', {'status': '已成交', 'notes': '越权'}).status_code == 403
    assert post(client, '/talents/1/activity', {'notes': '越权'}).status_code == 403
    login(client, 'staff')
    for status in ['已联系', '已回复', '已寄样', '已拍摄', '已发布', '已成交']:
        assert post(client, '/talents/1/status', {'status': status, 'notes': '测试变更依据'}).status_code == 302
    assert rows(app, 'SELECT status FROM talents') == [('已成交',)]
    assert len(rows(app, "SELECT * FROM activities WHERE kind='进度变更' AND user_id=2")) == 6
    post(client, '/talents/1/status', {'status': '无效状态', 'notes': '测试'})
    assert rows(app, 'SELECT status FROM talents') == [('已成交',)]


def test_contact_followup_and_staff_statistics(app, client):
    login(client)
    create_talent(client)
    login(client, 'staff')
    response = post(client, '/talents/1/activity', {'contacted_at': '2020-01-01T10:00', 'followup_at': '2020-01-02T10:00', 'followup_state': '待跟进', 'reply': '测试回复', 'notes': '测试联系记录'})
    assert response.status_code == 302
    assert '测试回复' in client.get('/talents/1').text
    assert '测试专用达人' in client.get('/').text
    assert rows(app, "SELECT user_id,kind FROM activities WHERE kind='商务联系'") == [(2, '商务联系')]
    post(client, '/talents/1/activity', {'contacted_at': '2020-01-03T10:00', 'followup_state': '已完成', 'notes': '测试完成跟进'})
    assert '暂无已到期的跟进计划' in client.get('/').text
    post(client, '/talents/1/activity', {'contacted_at': '2099-01-03T10:00', 'followup_state': '已完成', 'notes': '测试未来时间'})
    assert rows(app, "SELECT COUNT(*) FROM activities WHERE kind='商务联系'") == [(2,)]


def test_claim_does_not_steal(app, client):
    login(client)
    create_talent(client, owner_id='')
    login(client, 'staff')
    post(client, '/talents/1/claim')
    assert rows(app, 'SELECT owner_id FROM talents') == [(2,)]
    login(client, 'other')
    post(client, '/talents/1/claim')
    assert rows(app, 'SELECT owner_id FROM talents') == [(2,)]


def test_invitation_only_uses_recorded_data(client):
    login(client)
    create_talent(client, fans='', historical_gmv='', sales_period='', categories='', content_types='')
    response = post(client, '/talents/1/invitation', {'product': '测试产品', 'offer': ''})
    assert response.status_code == 200
    assert '测试专用达人您好' in response.text
    assert '寄样、内容要求和佣金条件可进一步沟通' in response.text
    assert '您资料中记录的带货类目为' not in response.text


def test_csv_import_dedup_errors_and_retry(app, client):
    login(client)
    content = '达人昵称,抖音号,粉丝数量,带货类目\n测试一,test_a,100,测试类目；测试类目\n测试重复,TEST_A,200,测试类目\n测试非法,test_b,-1,测试类目\n测试缺失,,20,测试类目\n'
    for _ in range(2):
        response = post(client, '/import', {'file': (io.BytesIO(content.encode('utf-8-sig')), 'test.csv')}, content_type='multipart/form-data')
        assert response.status_code == 200
        assert '失败行' in response.text and '粉丝数量必须为非负数字' in response.text
    assert rows(app, 'SELECT COUNT(*),categories FROM talents') == [(1, '测试类目')]
    assert client.get('/import/template.csv').data.startswith(b'\xef\xbb\xbf')
    assert len(client.get('/import/template.csv').text.strip().splitlines()) == 1


def test_excel_and_formula_rejection(app, client):
    login(client)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['达人昵称', '抖音号', '粉丝数量'])
    sheet.append(['测试Excel', 'test_xlsx', 200])
    sheet.append(['=1+1', 'test_formula', 20])
    output = io.BytesIO()
    workbook.save(output)
    response = post(client, '/import', {'file': (io.BytesIO(output.getvalue()), 'test.xlsx')}, content_type='multipart/form-data')
    assert response.status_code == 200
    assert '不接受公式' in response.text
    assert rows(app, 'SELECT douyin_id,fans FROM talents') == [('test_xlsx', 200)]


def test_malformed_file_and_request_limit(app, client):
    login(client)
    response = post(client, '/import', {'file': (io.BytesIO(b'invalid'), 'bad.xlsx')}, content_type='multipart/form-data')
    assert '无法读取Excel' in response.text
    response = post(client, '/import', {'file': (io.BytesIO(b'x' * (5*1024*1024)), 'big.csv')}, content_type='multipart/form-data')
    assert response.status_code == 413
    assert rows(app, 'SELECT COUNT(*) FROM talents') == [(0,)]


def test_api_and_screening(client):
    login(client)
    create_talent(client)
    product = dict(min_fans='5000', max_fans='20000', target_gmv='1000', category='测试类目', content_type='测试内容', sales_period='测试周期')
    response = post(client, '/api/v1/talents/1/score', json=product)
    assert response.json['total'] == 100
    assert response.json['coverage'] == 100
    assert '综合分 / 100' in post(client, '/screening', product).text
    product['sales_period'] = '不同测试周期'
    response = post(client, '/api/v1/talents/1/score', json=product)
    assert response.json['total'] is None
    assert response.json['coverage'] == 75
    assert response.json['dimensions'][2]['points'] is None
    assert post(client, '/api/v1/talents/1/score', json=[]).status_code == 400
    assert client.get('/api/v1/capabilities').json['automatic_contact_enabled'] is False
    assert client.get('/api/v1/talents').json['items'][0]['douyin_id'] == 'test_only_01'


def test_xss_is_escaped(client):
    login(client)
    create_talent(client, nickname='<script>alert(1)</script>')
    response = client.get('/talents/1')
    assert '<script>alert(1)</script>' not in response.text
    assert '&lt;script&gt;' in response.text


def test_accounts_password_change_and_login_throttle(client):
    login(client)
    post(client, '/users', dict(username='new_staff', display_name='测试员工', password='NewPassword123!', role='staff'))
    assert post(client, '/login', {'username': 'new_staff', 'password': 'NewPassword123!'}).status_code == 302
    response = post(client, '/account', {'old_password': 'NewPassword123!', 'new_password': 'UpdatedPassword123!'})
    assert '密码已更新' in response.text
    post(client, '/logout')
    assert post(client, '/login', {'username': 'new_staff', 'password': 'UpdatedPassword123!'}).status_code == 302
    post(client, '/logout')
    for _ in range(10):
        assert post(client, '/login', {'username': 'admin', 'password': 'bad'}).status_code == 200
    assert post(client, '/login', {'username': 'admin', 'password': 'bad'}).status_code == 429


def test_admin_cli_rejects_overwrite(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=['init-admin', '--username', 'admin', '--password', 'TestPassword123!'])
    assert result.exit_code != 0
    assert '账号已存在' in result.output
