#!/usr/bin/python
# coding=utf-8
"""
基于 Flask 框架开发的股票相关 Web 应用程序，核心功能是提供股票行情、个股分析与选股推荐等页面访问
指定模板文件夹为 templates（存放 HTML 文件）、静态资源文件夹为 static（存放图片 / CSS/JS）；
"""

from flask import Flask, render_template, redirect  #导入 Flask 核心库、render_template（渲染 HTML 模板）
from user import user_blueprint, is_login, is_admin  #自定义的 user 蓝图模块。
from api import api_blueprint              #自定义的 api 蓝图模块。
import functools   #functools（装饰器工具）
from flask_cors import CORS  #flask_cors（跨域支持）
app = Flask(__name__, template_folder='templates', static_folder='static') #所有的HTML网页都放在tem文件夹里，所有的图片，样式都放在sta文件夹里
CORS(app)  # 允许所有来源的请求访问

# 校验用户是否登录
def check_login_wrapper(fn):
    @functools.wraps(fn)  #保留原函数的元信息（如函数名），避免装饰器覆盖导致的调试问题。

    def wrapper(*args, **kwargs):
        if not is_login():  #调用 is_login() 判断登录状态
            return render_template('index.html')  #未登录：跳转到 index.html（首页 / 登录页）
        else:
            return fn(*args, **kwargs)  # 让原函数能正常接收参数，不影响功能

    return wrapper


def check_admin_wrapper(fn):
    """已登录且为管理员才可访问（与 check_login_wrapper 组合使用）。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_login() or not is_admin():
            return redirect('/')
        return fn(*args, **kwargs)

    return wrapper


# 页面跳转
#无需登录   首页
@app.route('/')  #页面路由
def index():
    return render_template('index.html')

#无需登录  注册页
@app.route('/register')
def register():
    return render_template('register.html')

#无需登录  登录页
@app.route('/login')
def login():
    return render_template('login.html')

#需要登录  大盘页面
@app.route('/dapan')
@check_login_wrapper
def dapan():
    return render_template('dapan.html')

#需要登录  个股量化分析页面
@app.route('/stock_info')
@check_login_wrapper
def stock_info():
    return render_template('stock_info.html')

#需要登录  大模型辅助选股
@app.route('/stock_recommend')
@check_login_wrapper
def stock_recommend():
    return render_template('stock_recommend.html')


#需要登录  收藏夹
@app.route('/favorites')
@check_login_wrapper
def favorites():
    return render_template('favorites.html')


#需要登录  量化风控
@app.route('/risk_control')
@check_login_wrapper
def risk_control():
    return render_template('risk_control.html')


#需要登录  量化策略（占位）
@app.route('/quant_strategy')
@check_login_wrapper
def quant_strategy():
    return render_template('quant_strategy.html')


@app.route('/active_market')
@check_login_wrapper
def active_market_redirect():
    return redirect('/risk_control')


# 管理员：注册用户管理
@app.route('/admin_users')
@check_login_wrapper
@check_admin_wrapper
def admin_users():
    return render_template('admin_users.html')


# API 接口注册
# 用户相关接口（如登录、注册、退出），路由前缀 /user（如 /user/login）；
app.register_blueprint(user_blueprint, url_prefix='/user')
# 股票相关接口，路由前缀 /api；
app.register_blueprint(api_blueprint, url_prefix='/api')

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5000, debug=False)
    # host='127.0.0.1'：仅本地可访问
    # 5000 是 Flask 框架的默认开发端口。
