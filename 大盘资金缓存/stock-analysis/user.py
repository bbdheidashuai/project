#!/usr/bin/python
# coding=utf-8
import sqlite3  # Python 内置的 SQLite 数据库操作模块，用于本地轻量级数据库管理；
# jsonify：Flask 提供的工具，用于将字典转换为 JSON 格式的 HTTP 响应；
# Blueprint：Flask 的蓝图机制，用于拆分模块化的路由
from datetime import datetime

from flask import jsonify, Blueprint, request

# 蓝图初始化：创建名为 user 的蓝图对象 user_blueprint，后续所有用户相关路由都注册到该蓝图上。
user_blueprint = Blueprint('user', __name__)

USER_DB = 'user_info.db'

# login_name 用于存储当前登录的用户名，初始为 None（表示未登录）。
login_name = None
# 当前登录用户是否为管理员（与 login_name 同步维护）
login_is_admin = False


def is_login():
    return login_name is not None


def is_admin():
    return is_login() and login_is_admin


def _ensure_user_schema(conn):
    """创建或升级 user 表，保证存在 is_admin 字段，并在无管理员时指定一名管理员。"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE user(
                name CHAR(256),
                password CHAR(256),
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.commit()
        return
    cur.execute('PRAGMA table_info(user)')
    cols = {row[1] for row in cur.fetchall()}
    if 'is_admin' not in cols:
        cur.execute('ALTER TABLE user ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0')
        conn.commit()
        cur.execute('SELECT COUNT(*) FROM user WHERE is_admin=1')
        if cur.fetchone()[0] == 0:
            cur.execute('UPDATE user SET is_admin=1 WHERE rowid = (SELECT MIN(rowid) FROM user)')
            conn.commit()


def _ensure_favorite_schema(conn):
    """用户自选股收藏表：按用户名 + 股票代码唯一。"""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS favorite(
            user_name TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            stock_board TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_name, stock_code)
        )
        """
    )
    conn.commit()


def _norm_stock_code(code):
    s = str(code).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _require_login_json():
    if not is_login():
        return jsonify({"success": False, "info": "请先登录"}), 401
    return None


def _admin_count(cur):
    cur.execute('SELECT COUNT(*) FROM user WHERE is_admin=1')
    return int(cur.fetchone()[0])


@user_blueprint.route('/check_login')  #检查登录状态接口
def check_login():
    """判断用户是否登录"""
    return jsonify({'username': login_name, 'login': is_login(), 'is_admin': bool(login_is_admin)})


@user_blueprint.route('/register/<name>/<password>')  #定义Flask注册接口路由。前端访问 register/用户名/密码 即可完成注册。
def register(name, password):
    conn = sqlite3.connect(USER_DB)
    cursor = conn.cursor()
    _ensure_user_schema(conn)

    cursor.execute('SELECT 1 FROM user WHERE name=?', (name,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'info': '该用户名已被注册！', 'success': False})

    cursor.execute('SELECT COUNT(*) FROM user')
    first_user = cursor.fetchone()[0] == 0
    is_adm = 1 if first_user else 0
    cursor.execute(
        'INSERT INTO user (name, password, is_admin) VALUES (?,?,?)',
        (name, password, is_adm),
    )
    conn.commit()
    conn.close()
    if first_user:
        return jsonify({'info': '用户注册成功！您为首位用户，已自动设为管理员。', 'success': True})
    return jsonify({'info': '用户注册成功！', 'success': True})


@user_blueprint.route('/login/<name>/<password>')  #定义 Flask 登录接口路由。前端访问 /login/用户名/密码 即可提交登录请求。
def login(name, password):
    global login_name, login_is_admin
    conn = sqlite3.connect(USER_DB)
    cursor = conn.cursor()
    _ensure_user_schema(conn)

    cursor.execute(
        'SELECT name, is_admin FROM user WHERE name=? AND password=?',
        (name, password),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        login_name = name
        login_is_admin = bool(row[1])
        return jsonify({'info': name + '用户登录成功！', 'success': True, 'is_admin': login_is_admin})
    return jsonify({'info': '用户名或密码错误！', 'success': False, 'is_admin': False})


@user_blueprint.route('/admin_login/<name>/<password>')
def admin_login(name, password):
    """管理员入口：校验账号密码且必须为管理员才建立会话。"""
    global login_name, login_is_admin
    conn = sqlite3.connect(USER_DB)
    cursor = conn.cursor()
    _ensure_user_schema(conn)

    cursor.execute(
        'SELECT name, is_admin FROM user WHERE name=? AND password=?',
        (name, password),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'info': '用户名或密码错误！', 'success': False, 'is_admin': False})
    if not row[1]:
        return jsonify({'info': '该账号不是管理员，请改用「用户登录」。', 'success': False, 'is_admin': False})
    login_name = name
    login_is_admin = True
    return jsonify({'info': name + '管理员登录成功！', 'success': True, 'is_admin': True})


@user_blueprint.route('/logout')
def logout():
    """用户登出"""
    global login_name, login_is_admin
    uname = login_name or ''
    resp = {'info': (uname + '用户已退出登录！') if uname else '已退出登录！', 'success': True}
    login_name = None
    login_is_admin = False
    return jsonify(resp)


def _admin_api_guard():
    if not is_admin():
        return jsonify({'success': False, 'info': '需要管理员权限'}), 403
    return None


@user_blueprint.route('/admin/list')
def admin_list_users():
    err = _admin_api_guard()
    if err:
        return err
    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    cur.execute('SELECT name, is_admin FROM user ORDER BY name')
    rows = [{'name': r[0], 'is_admin': bool(r[1])} for r in cur.fetchall()]
    conn.close()
    return jsonify({'success': True, 'users': rows})


@user_blueprint.route('/admin/delete')
def admin_delete_user():
    err = _admin_api_guard()
    if err:
        return err
    target = request.args.get('name', '').strip()
    if not target:
        return jsonify({'success': False, 'info': '缺少参数 name'})
    if target == login_name:
        return jsonify({'success': False, 'info': '不能删除当前登录账号'})
    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    cur.execute('SELECT is_admin FROM user WHERE name=?', (target,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'info': '用户不存在'})
    if row[0] and _admin_count(cur) <= 1:
        conn.close()
        return jsonify({'success': False, 'info': '不能删除唯一的管理员账号'})
    _ensure_favorite_schema(conn)
    cur.execute("DELETE FROM favorite WHERE user_name=?", (target,))
    cur.execute('DELETE FROM user WHERE name=?', (target,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'info': '已删除用户：' + target})


@user_blueprint.route('/admin/set_admin')
def admin_set_admin():
    global login_is_admin
    err = _admin_api_guard()
    if err:
        return err
    target = request.args.get('name', '').strip()
    val_raw = request.args.get('value', '')
    if not target or val_raw not in ('0', '1'):
        return jsonify({'success': False, 'info': '缺少参数 name 或 value（0/1）'})
    new_flag = int(val_raw)
    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    cur.execute('SELECT is_admin FROM user WHERE name=?', (target,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'info': '用户不存在'})
    if new_flag == 0 and row[0] and _admin_count(cur) <= 1:
        conn.close()
        return jsonify({'success': False, 'info': '系统至少需要保留一名管理员'})
    cur.execute('UPDATE user SET is_admin=? WHERE name=?', (new_flag, target))
    conn.commit()
    conn.close()
    if target == login_name:
        login_is_admin = bool(new_flag)
    return jsonify({'success': True, 'info': '已更新管理员状态'})


@user_blueprint.route("/favorites/add", methods=["POST"])
def favorites_add():
    err = _require_login_json()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    code = _norm_stock_code(body.get("code", ""))
    name = (body.get("name") or "").strip()
    board = (body.get("board") or "").strip()
    if not code or not name:
        return jsonify({"success": False, "info": "缺少股票代码或名称"})

    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    _ensure_favorite_schema(conn)
    try:
        cur.execute(
            """
            INSERT INTO favorite (user_name, stock_code, stock_name, stock_board, created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                login_name,
                code,
                name,
                board,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "info": "该股票已在收藏夹中"})
    conn.close()
    return jsonify({"success": True, "info": "已加入收藏"})


@user_blueprint.route("/favorites/list")
def favorites_list():
    err = _require_login_json()
    if err:
        return err
    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    _ensure_favorite_schema(conn)
    cur.execute(
        """
        SELECT stock_code, stock_name, stock_board, created_at
        FROM favorite
        WHERE user_name=?
        ORDER BY created_at DESC
        """,
        (login_name,),
    )
    rows = [
        {"code": r[0], "name": r[1], "board": r[2] or "", "created_at": r[3]}
        for r in cur.fetchall()
    ]
    conn.close()
    return jsonify({"success": True, "items": rows})


@user_blueprint.route("/favorites/delete", methods=["POST"])
def favorites_delete():
    err = _require_login_json()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    code = _norm_stock_code(body.get("code", ""))
    if not code:
        return jsonify({"success": False, "info": "缺少股票代码"})

    conn = sqlite3.connect(USER_DB)
    cur = conn.cursor()
    _ensure_user_schema(conn)
    _ensure_favorite_schema(conn)
    cur.execute(
        "DELETE FROM favorite WHERE user_name=? AND stock_code=?",
        (login_name, code),
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    if deleted == 0:
        return jsonify({"success": False, "info": "收藏中未找到该股票"})
    return jsonify({"success": True, "info": "已从收藏夹移除"})
