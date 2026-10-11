import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from domain import FOLLOWUP_STATES, HEADERS, STATUSES, invitation, numeric, read_import, score_talent, validate_talent

TZ = ZoneInfo('Asia/Shanghai')


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app_database, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith('/api/'):
                return jsonify(error='请先登录'), 401
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user['role'] != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def create_app(config=None):
    root = Path(__file__).resolve().parent
    instance = Path(os.environ.get('MCN_INSTANCE_DIR', str(root / 'instance')))
    app = Flask(__name__, instance_path=str(instance))
    app.config.from_mapping(DATABASE=str(instance / 'mcn.sqlite3'), MAX_CONTENT_LENGTH=5 * 1024 * 1024,
                            SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                            SESSION_COOKIE_SECURE=os.environ.get('MCN_HTTPS') == '1')
    if config:
        app.config.update(config)
    instance.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not app.config.get('SECRET_KEY'):
        key = instance / 'session.key'
        supplied = os.environ.get('MCN_SECRET_KEY')
        if supplied:
            app.config['SECRET_KEY'] = supplied
        else:
            try:
                fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'w') as file:
                    file.write(secrets.token_hex(32))
            app.config['SECRET_KEY'] = key.read_text().strip()
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript((root / 'schema.sql').read_text())

    @app.before_request
    def prepare():
        g.app_database = app.config['DATABASE']
        g.user = db().execute('SELECT * FROM users WHERE id=? AND active=1', (session.get('user_id'),)).fetchone()
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not secrets.compare_digest(str(token).encode('utf-8'), session['csrf'].encode('utf-8')):
                abort(400, description='表单已过期或校验失败，请刷新页面后重试')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        if g.get('user'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.teardown_appcontext
    def close(error):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()

    @app.context_processor
    def context():
        return {'statuses': STATUSES, 'followup_states': FOLLOWUP_STATES, 'current_user': g.get('user')}

    @app.template_filter('money')
    def money(value):
        return '数据不足' if value is None else f'{value / 100:,.2f}'

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def errors(error):
        messages = {400: getattr(error, 'description', '请求格式错误'), 403: '没有权限操作该记录', 404: '页面或记录不存在', 413: '文件超过5MB，请拆分后再导入'}
        if request.path.startswith('/api/'):
            return jsonify(error=messages[error.code]), error.code
        return render_template('error.html', message=messages[error.code]), error.code

    @app.cli.command('init-admin')
    @click.option('--username', default='admin', help='管理员登录账号')
    @click.option('--name', default='管理员', help='中文姓名')
    @click.password_option(prompt='管理员密码', confirmation_prompt='再次输入管理员密码', help='至少10位密码；交互输入不显示')
    def init_admin(username, name, password):
        if len(password) < 10:
            raise click.ClickException('密码至少10位')
        with sqlite3.connect(app.config['DATABASE']) as conn:
            try:
                conn.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                             (username, name, generate_password_hash(password), 'admin', now()))
            except sqlite3.IntegrityError:
                raise click.ClickException('账号已存在，不会覆盖现有账号') from None
        click.echo('管理员已创建，请打开网页登录。')

    @app.get('/health')
    def health():
        db().execute('SELECT COUNT(*) FROM talents').fetchone()
        return jsonify(status='ok', database='ok')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            cutoff = (datetime.now(TZ) - timedelta(minutes=15)).isoformat(timespec='seconds')
            address = request.remote_addr or 'unknown'
            with db():
                db().execute('DELETE FROM login_attempts WHERE attempted_at<?', (cutoff,))
            attempts = db().execute('SELECT COUNT(*) FROM login_attempts WHERE address=? AND attempted_at>=?', (address, cutoff)).fetchone()[0]
            if attempts >= 10:
                return render_template('error.html', message='登录失败次数过多，请15分钟后重试'), 429
            user = db().execute('SELECT * FROM users WHERE username=? AND active=1', (request.form.get('username', '').strip(),)).fetchone()
            if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
                session.clear()
                session['user_id'] = user['id']
                session['csrf'] = secrets.token_hex(32)
                return redirect(url_for('dashboard'))
            with db():
                db().execute('INSERT INTO login_attempts(address,attempted_at) VALUES(?,?)', (address, now()))
            flash('账号或密码错误', 'error')
        return render_template('login.html')

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        counts = {row['status']: row['n'] for row in db().execute('SELECT status,COUNT(*) n FROM talents GROUP BY status')}
        staff = db().execute('''SELECT u.id,u.display_name,u.role,
            (SELECT COUNT(*) FROM talents t WHERE t.owner_id=u.id) assigned,
            (SELECT COUNT(*) FROM talents t WHERE t.owner_id=u.id AND t.status='已成交') deals,
            (SELECT COUNT(*) FROM activities a WHERE a.user_id=u.id AND a.kind='商务联系') contacts,
            (SELECT COUNT(*) FROM activities a WHERE a.user_id=u.id AND a.kind='商务联系' AND a.created_at>=?) today_contacts
            FROM users u WHERE u.active=1 ORDER BY u.id''', (datetime.now(TZ).date().isoformat(),)).fetchall()
        # 每位达人仅取最近一条商务联系，旧的跟进计划不会重复提醒。
        followups = db().execute('''SELECT a.*,t.nickname,u.display_name FROM activities a
            JOIN talents t ON t.id=a.talent_id JOIN users u ON u.id=a.user_id
            WHERE a.id=(SELECT MAX(b.id) FROM activities b WHERE b.talent_id=a.talent_id AND b.kind='商务联系')
            AND a.followup_state IN ('待跟进','跟进中') AND a.followup_at IS NOT NULL AND a.followup_at<=?
            ORDER BY a.followup_at LIMIT 30''', (now(),)).fetchall()
        total = sum(counts.values())
        return render_template('dashboard.html', counts=counts, total=total, staff=staff, followups=followups)

    def talent_or_404(talent_id):
        talent = db().execute('SELECT t.*,u.display_name owner_name FROM talents t LEFT JOIN users u ON u.id=t.owner_id WHERE t.id=?', (talent_id,)).fetchone()
        if talent is None:
            abort(404)
        return talent

    def editable(talent):
        return g.user['role'] == 'admin' or talent['owner_id'] == g.user['id']

    def employees():
        return db().execute('SELECT id,display_name FROM users WHERE active=1 ORDER BY id').fetchall()

    def owner_from_form():
        if g.user['role'] != 'admin':
            return g.user['id']
        value = request.form.get('owner_id', '')
        if not value:
            return None
        if not value.isdigit() or not db().execute('SELECT 1 FROM users WHERE id=? AND active=1', (value,)).fetchone():
            raise ValueError('请选择有效的负责人')
        return int(value)

    def insert_talent(data, owner):
        fields = list(data)
        stamp = now()
        conn = db()
        cursor = conn.execute(f'INSERT INTO talents({",".join(fields)},owner_id,created_by,created_at,updated_at) VALUES({",".join("?" for _ in range(len(fields)+4))})',
                              (*data.values(), owner, g.user['id'], stamp, stamp))
        conn.execute('INSERT INTO activities(talent_id,user_id,kind,notes,created_at) VALUES(?,?,?,?,?)', (cursor.lastrowid, g.user['id'], '创建档案', '录入真实达人资料', stamp))
        return cursor.lastrowid

    @app.get('/talents')
    @login_required
    def talents():
        query, status, category, owner = [request.args.get(k, '').strip() for k in ('q', 'status', 'category', 'owner')]
        conditions, params = [], []
        if query:
            conditions.append('(t.nickname LIKE ? OR t.douyin_id LIKE ?)')
            params.extend(['%' + query + '%'] * 2)
        if status:
            conditions.append('t.status=?')
            params.append(status)
        if category:
            conditions.append('t.categories LIKE ?')
            params.append('%' + category + '%')
        if owner:
            conditions.append('t.owner_id=?')
            params.append(owner)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        page = max(1, request.args.get('page', 1, type=int) or 1)
        total = db().execute('SELECT COUNT(*) FROM talents t' + where, params).fetchone()[0]
        rows = db().execute('SELECT t.*,u.display_name owner_name FROM talents t LEFT JOIN users u ON u.id=t.owner_id' + where + ' ORDER BY t.updated_at DESC,t.id DESC LIMIT 30 OFFSET ?', (*params, (page-1)*30)).fetchall()
        return render_template('talents.html', talents=rows, total=total, page=page, employees=employees())

    @app.route('/talents/new', methods=['GET', 'POST'])
    @login_required
    def talent_new():
        if request.method == 'POST':
            try:
                data = validate_talent(request.form)
                owner = owner_from_form()
                with db():
                    talent_id = insert_talent(data, owner)
                flash('达人档案已创建', 'success')
                return redirect(url_for('talent_detail', talent_id=talent_id))
            except (ValueError, sqlite3.IntegrityError) as error:
                flash(str(error) if isinstance(error, ValueError) else '该抖音号已存在，请查看已有档案', 'error')
        return render_template('talent_form.html', talent=None, form=request.form, employees=employees())

    @app.route('/talents/<int:talent_id>/edit', methods=['GET', 'POST'])
    @login_required
    def talent_edit(talent_id):
        talent = talent_or_404(talent_id)
        if not editable(talent):
            abort(403)
        if request.method == 'POST':
            try:
                data = validate_talent(request.form)
                owner = owner_from_form() if g.user['role'] == 'admin' else talent['owner_id']
                with db():
                    db().execute(f'UPDATE talents SET {",".join(f"{k}=?" for k in data)},owner_id=?,updated_at=? WHERE id=?', (*data.values(), owner, now(), talent_id))
                    db().execute('INSERT INTO activities(talent_id,user_id,kind,notes,created_at) VALUES(?,?,?,?,?)', (talent_id, g.user['id'], '修改档案', '更新档案资料或负责人', now()))
                flash('档案已更新', 'success')
                return redirect(url_for('talent_detail', talent_id=talent_id))
            except (ValueError, sqlite3.IntegrityError) as error:
                flash(str(error) if isinstance(error, ValueError) else '该抖音号已存在', 'error')
        form = request.form if request.method == 'POST' else dict(talent)
        if request.method != 'POST':
            form['historical_gmv'] = '' if talent['historical_gmv_cents'] is None else f'{talent["historical_gmv_cents"]/100:.2f}'
        return render_template('talent_form.html', talent=talent, form=form, employees=employees())

    @app.get('/talents/<int:talent_id>')
    @login_required
    def talent_detail(talent_id):
        talent = talent_or_404(talent_id)
        activities = db().execute('SELECT a.*,u.display_name FROM activities a JOIN users u ON u.id=a.user_id WHERE talent_id=? ORDER BY a.id DESC', (talent_id,)).fetchall()
        return render_template('talent_detail.html', talent=talent, activities=activities, can_edit=editable(talent), generated=None)

    @app.post('/talents/<int:talent_id>/claim')
    @login_required
    def claim(talent_id):
        talent_or_404(talent_id)
        with db():
            changed = db().execute('UPDATE talents SET owner_id=?,updated_at=? WHERE id=? AND owner_id IS NULL', (g.user['id'], now(), talent_id)).rowcount
            if changed:
                db().execute('INSERT INTO activities(talent_id,user_id,kind,notes,created_at) VALUES(?,?,?,?,?)', (talent_id, g.user['id'], '认领档案', '员工认领未分配档案', now()))
        flash('已认领档案' if changed else '档案已有负责人，未改变归属', 'success' if changed else 'error')
        return redirect(url_for('talent_detail', talent_id=talent_id))

    @app.post('/talents/<int:talent_id>/status')
    @login_required
    def change_status(talent_id):
        talent = talent_or_404(talent_id)
        if not editable(talent):
            abort(403)
        status = request.form.get('status')
        notes = request.form.get('notes', '').strip()
        if status not in STATUSES or not notes or len(notes) > 2000:
            flash('请选择有效状态，并填写2000字以内的变更依据', 'error')
        elif status != talent['status']:
            with db():
                db().execute('UPDATE talents SET status=?,updated_at=? WHERE id=?', (status, now(), talent_id))
                db().execute('INSERT INTO activities(talent_id,user_id,kind,old_status,new_status,notes,created_at) VALUES(?,?,?,?,?,?,?)', (talent_id, g.user['id'], '进度变更', talent['status'], status, notes, now()))
            flash('合作进度已更新，变更记录已保存', 'success')
        return redirect(url_for('talent_detail', talent_id=talent_id))

    def parse_time(value, label):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%dT%H:%M').replace(tzinfo=TZ).isoformat(timespec='seconds')
        except ValueError:
            raise ValueError(f'{label}格式不正确') from None

    @app.post('/talents/<int:talent_id>/activity')
    @login_required
    def add_activity(talent_id):
        talent = talent_or_404(talent_id)
        if not editable(talent):
            abort(403)
        try:
            contacted = parse_time(request.form.get('contacted_at'), '联系时间')
            followup = parse_time(request.form.get('followup_at'), '跟进时间')
            state = request.form.get('followup_state')
            reply, notes = request.form.get('reply', '').strip(), request.form.get('notes', '').strip()
            if not contacted or not notes or state not in FOLLOWUP_STATES or max(len(reply), len(notes)) > 2000:
                raise ValueError('请填写联系时间、联系内容和有效的跟进状态，文本最多2000字')
            if contacted > now():
                raise ValueError('联系时间不能晚于当前时间')
            if followup and followup < contacted:
                raise ValueError('下次跟进时间不能早于联系时间')
            with db():
                db().execute('INSERT INTO activities(talent_id,user_id,kind,contacted_at,reply,followup_at,followup_state,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)', (talent_id, g.user['id'], '商务联系', contacted, reply, followup, state, notes, now()))
                db().execute('UPDATE talents SET updated_at=? WHERE id=?', (now(), talent_id))
            flash('联系及跟进记录已保存；合作进度请按真实情况单独更新', 'success')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('talent_detail', talent_id=talent_id))

    @app.post('/talents/<int:talent_id>/invitation')
    @login_required
    def generate_invitation(talent_id):
        talent = talent_or_404(talent_id)
        product, offer = request.form.get('product', '').strip(), request.form.get('offer', '').strip()
        if not product or len(product) > 300 or len(offer) > 2000:
            flash('请填写产品名称，产品最多300字，合作条件最多2000字', 'error')
            return redirect(url_for('talent_detail', talent_id=talent_id))
        generated = invitation(talent, product, offer, g.user['display_name'])
        activities = db().execute('SELECT a.*,u.display_name FROM activities a JOIN users u ON u.id=a.user_id WHERE talent_id=? ORDER BY a.id DESC', (talent_id,)).fetchall()
        return render_template('talent_detail.html', talent=talent, activities=activities, can_edit=editable(talent), generated=generated)

    def product_from_form(form):
        low, high = numeric(form.get('min_fans'), '最低粉丝数'), numeric(form.get('max_fans'), '最高粉丝数')
        target = numeric(form.get('target_gmv'), '目标销售额', money=True)
        category, content_type, period = [str(form.get(k) or '').strip() for k in ('category', 'content_type', 'sales_period')]
        if low is None or high is None or high <= 0 or high < low or not target or not all((category, content_type, period)):
            raise ValueError('请完整填写筛选条件：最高粉丝数和目标销售额必须大于0，最高粉丝数不能低于最低值')
        if any(len(s) > 300 for s in (category, content_type, period)):
            raise ValueError('筛选条件最多300字')
        return dict(min_fans=low, max_fans=high, target_gmv_cents=target, category=category, content_type=content_type, sales_period=period)

    @app.route('/screening', methods=['GET', 'POST'])
    @login_required
    def screening():
        results = None
        if request.method == 'POST':
            try:
                product = product_from_form(request.form)
                results = [{'talent': talent, 'score': score_talent(talent, product)} for talent in db().execute('SELECT * FROM talents ORDER BY id')]
                results.sort(key=lambda r: (r['score']['coverage'], r['score']['observed']), reverse=True)
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('screening.html', results=results, form=request.form)

    @app.route('/import', methods=['GET', 'POST'])
    @login_required
    def import_data():
        report = None
        if request.method == 'POST':
            uploaded = request.files.get('file')
            try:
                if uploaded is None or not uploaded.filename:
                    raise ValueError('请选择CSV或Excel文件')
                rows = read_import(uploaded.read(), uploaded.filename)
                owner = owner_from_form()
                report = {'created': 0, 'duplicates': 0, 'errors': []}
                with db():
                    for line, row in rows:
                        try:
                            if any(str(v or '').lstrip().startswith(('=', '+', '@')) for v in row.values()):
                                raise ValueError('不接受公式或以=、+、@开头的单元格，请转换为纯文本')
                            data = validate_talent(row)
                            if db().execute('SELECT 1 FROM talents WHERE douyin_id=? COLLATE NOCASE', (data['douyin_id'],)).fetchone():
                                report['duplicates'] += 1
                                continue
                            insert_talent(data, owner)
                            report['created'] += 1
                        except ValueError as error:
                            report['errors'].append({'line': line, 'message': str(error)})
                flash('导入完成，请查看新增、重复跳过和失败行统计', 'success')
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('import.html', report=report, employees=employees())

    @app.get('/import/template.csv')
    @login_required
    def import_template():
        output = io.StringIO()
        csv.writer(output).writerow(HEADERS.keys())
        return app.response_class('\ufeff' + output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=talents-template.csv'})

    @app.route('/users', methods=['GET', 'POST'])
    @admin_required
    def users():
        if request.method == 'POST':
            username, name, password = [request.form.get(k, '').strip() for k in ('username', 'display_name', 'password')]
            role = request.form.get('role')
            if not username or not name or len(username) > 100 or len(name) > 100 or len(password) < 10 or role not in ('admin', 'staff'):
                flash('账号及姓名为必填、最多100字，密码至少10位，请选择有效角色', 'error')
            else:
                try:
                    with db():
                        db().execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)', (username, name, generate_password_hash(password), role, now()))
                    flash('员工账号已创建', 'success')
                    return redirect(url_for('users'))
                except sqlite3.IntegrityError:
                    flash('登录账号已存在', 'error')
        return render_template('users.html', users=db().execute('SELECT id,username,display_name,role FROM users ORDER BY id').fetchall())

    @app.route('/account', methods=['GET', 'POST'])
    @login_required
    def account():
        if request.method == 'POST':
            old, new = request.form.get('old_password', ''), request.form.get('new_password', '')
            if not check_password_hash(g.user['password_hash'], old) or len(new) < 10:
                flash('原密码错误，或新密码不足10位', 'error')
            else:
                with db():
                    db().execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(new), g.user['id']))
                session['csrf'] = secrets.token_hex(32)
                flash('密码已更新', 'success')
        return render_template('account.html')

    @app.get('/api/v1/capabilities')
    @login_required
    def capabilities():
        return jsonify(version=1, features=['talent_read', 'explainable_scoring'], public_collection_enabled=False, automatic_contact_enabled=False,
                       message='预留采集和联系适配器接口；当前版本不采集、不发送消息，接入前需核验授权、平台规则及个人信息处理依据。')

    @app.get('/api/v1/talents')
    @login_required
    def api_talents():
        after = max(0, request.args.get('after_id', 0, type=int) or 0)
        rows = db().execute('SELECT id,nickname,douyin_id,fans,categories,content_types,historical_gmv_cents,sales_period,status FROM talents WHERE id>? ORDER BY id LIMIT 100', (after,)).fetchall()
        return jsonify(items=[dict(r) for r in rows], next_after_id=rows[-1]['id'] if rows else None)

    @app.post('/api/v1/talents/<int:talent_id>/score')
    @login_required
    def api_score(talent_id):
        talent = talent_or_404(talent_id)
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ValueError('请求正文必须为JSON对象')
            product = product_from_form(data)
            return jsonify(score_talent(talent, product))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    return app
