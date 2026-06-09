#!/usr/bin/python
# coding=utf-8
from flask import jsonify, Blueprint, request
import pandas as pd
import numpy as np
import json
import os
import time
from service.stock_spider import EastmoneySpider
from service import tech_util
from service import recommend_util
from service import llm_sector_advice
from service import compass_oamv
from service import active_amv_store
from service import quant_strategy
from service import quant_strategy_prefs
from service import quant_strategy_scan
import user
from user import is_login
import baostock as bs
from datetime import datetime, timedelta


api_blueprint = Blueprint('api', __name__)  #创建接口模块，所有股票接口都挂在这个模块下。

em_spider = EastmoneySpider()  #创建东方财富爬虫对象，爬取股票数据。

# 代理可选：环境变量 PROXY_URL；未设置则不使用代理（直连更稳定）
_DEFAULT_PROXY_URL = "http://15732052323:AjX88pR9@t117.juliangip.cc:31929"


def _get_proxy_url():
    env_val = os.environ.get('PROXY_URL')
    if env_val is not None:
        return env_val.strip() or None
    return _DEFAULT_PROXY_URL


proxy_url = _get_proxy_url()

KLINE_CACHE_DIR = "./dataset/kline"
CLOSE_HOUR = 15
SCAN_FETCH_DAYS = 250  # 选股扫描联网拉取天数（覆盖 MA114 等指标即可）

_bs_session_depth = 0

_PERIOD_CFG = {
    'day': {'suffix': '', 'baostock_freq': 'd', 'fetch_days': 1200, 'label': '日K', 'name': '日线'},
    'week': {'suffix': '_w', 'baostock_freq': 'w', 'fetch_days': 1200 * 7, 'label': '周K', 'name': '周线'},
    'month': {'suffix': '_m', 'baostock_freq': 'm', 'fetch_days': 1200 * 31, 'label': '月K', 'name': '月线'},
    'quarter': {
        'suffix': '_q', 'baostock_freq': 'd', 'fetch_days': 1200 * 7,
        'resample': 'quarter', 'label': '季K', 'name': '季线',
    },
}

_RECOMMEND_BOARD_CACHE = {"ts": 0.0, "boards": []}


def _normalize_period(period):
    p = (period or 'day').lower().strip()
    return p if p in _PERIOD_CFG else 'day'


def _kline_cache_path(code, period='day'):
    os.makedirs(KLINE_CACHE_DIR, exist_ok=True)
    suffix = _PERIOD_CFG[_normalize_period(period)]['suffix']
    return os.path.join(KLINE_CACHE_DIR, f"{code}{suffix}.csv")


def _read_kline_cache(code, period='day'):
    cache_path = _kline_cache_path(code, period)
    if not os.path.exists(cache_path):
        return None

    try:
        cache_df = pd.read_csv(cache_path, encoding='utf8')
    except Exception:
        return None

    required_columns = {'date', 'open', 'close', 'high', 'low', 'volume'}
    if cache_df.empty or not required_columns.issubset(set(cache_df.columns)):
        return None

    for col in ['open', 'close', 'high', 'low', 'volume']:
        cache_df[col] = pd.to_numeric(cache_df[col], errors='coerce')
    cache_df.dropna(subset=['date', 'open', 'close', 'high', 'low', 'volume'], inplace=True)

    if cache_df.empty:
        return None
    return cache_df


def _to_baostock_code(code):
    if code == '000001':
        return 'sh.000001'
    if code == '000852':
        return 'sh.000852'
    if code == '399001':
        return 'sz.399001'
    if code == '399005':
        return 'sz.399005'
    if code == '399006':
        return 'sz.399006'
    if code == '399300':
        return 'sh.000300'
    if code == '899050':
        return 'bj.899050'
    if code.startswith('6'):
        return f'sh.{code}'
    if code.startswith('0') or code.startswith('3'):
        return f'sz.{code}'
    if code.startswith('4') or code.startswith('8'):
        return f'bj.{code}'
    return f'sh.{code}'


def _get_latest_cache_date(cache_df):
    if cache_df is None or cache_df.empty or 'date' not in cache_df.columns:
        return None
    dates = pd.to_datetime(cache_df['date'], errors='coerce').dropna()
    if dates.empty:
        return None
    return dates.max().date()


def _get_last_friday(current_date):
    # Monday=0 ... Sunday=6
    weekday = current_date.weekday()
    if weekday == 5:
        # Saturday -> Friday
        return current_date - timedelta(days=1)
    if weekday == 6:
        # Sunday -> Friday
        return current_date - timedelta(days=2)
    # 工作日时返回本周最近一个周五（含当天为周五）
    return current_date - timedelta(days=(weekday - 4))


def _resample_to_quarter(stock_df):
    """由日线聚合为季线（日历季度末）。"""
    df = stock_df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df.dropna(subset=['date'], inplace=True)
    df.sort_values('date', inplace=True)
    df.set_index('date', inplace=True)
    agg = df.resample('QE').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    agg = agg.reset_index()
    agg['date'] = agg['date'].dt.strftime('%Y-%m-%d')
    return agg[['date', 'open', 'close', 'low', 'high', 'volume']]


def baostock_session_begin():
    """批量拉取 K 线时复用 baostock 会话，避免每只股票 login/logout。"""
    global _bs_session_depth
    if _bs_session_depth == 0:
        lg = bs.login()
        if lg.error_code != '0':
            raise Exception(f"baostock 登录失败: {lg.error_msg}")
    _bs_session_depth += 1


def baostock_session_end():
    global _bs_session_depth
    if _bs_session_depth <= 0:
        return
    _bs_session_depth -= 1
    if _bs_session_depth == 0:
        bs.logout()


def _fetch_kline_from_baostock(code, days=1200, end_date=None, period='day'):
    period = _normalize_period(period)
    cfg = _PERIOD_CFG[period]
    external_session = _bs_session_depth > 0
    if not external_session:
        lg = bs.login()
        if lg.error_code != '0':
            raise Exception(f"baostock 登录失败: {lg.error_msg}")
    try:
        bs_code = _to_baostock_code(code)
        end_dt = end_date if end_date is not None else datetime.now().date()
        start_date = (end_dt - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date_str = end_dt.strftime('%Y-%m-%d')

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date_str,
            frequency=cfg['baostock_freq'],
            adjustflag="3"
        )
        if rs.error_code != '0':
            raise Exception(f"数据查询失败: {rs.error_msg}")

        stock_df = rs.get_data()
        if stock_df.empty:
            raise Exception("未获取到任何数据")

        for col in ['open', 'close', 'high', 'low', 'volume']:
            #stock_df[col] = stock_df[col].astype(float)
            stock_df[col] = pd.to_numeric(stock_df[col], errors='coerce')
        stock_df = stock_df[['date', 'open', 'close', 'low', 'high', 'volume']]
        if cfg.get('resample') == 'quarter':
            stock_df = _resample_to_quarter(stock_df)
            if stock_df.empty:
                raise Exception("季线聚合后无数据")
        return stock_df
    finally:
        if not external_session:
            bs.logout()


def get_kline_with_cache(code, days=None, period='day', cache_only=False, allow_stale=False, quiet=False):
    period = _normalize_period(period)
    cfg = _PERIOD_CFG[period]
    if days is None:
        days = cfg['fetch_days']
    cache_df = _read_kline_cache(code, period)
    now = datetime.now()
    today = now.date()
    weekday = today.weekday()  # Monday=0 ... Sunday=6
    latest_cache_date = _get_latest_cache_date(cache_df)

    def _log(msg):
        if not quiet:
            print(msg)

    if cache_only:
        return cache_df

    if allow_stale and cache_df is not None and not cache_df.empty:
        return cache_df

    _log(
        f"[KLINE] 请求 code={code}, period={period}, "
        f"now={now.strftime('%Y-%m-%d %H:%M:%S')}, weekday={weekday}, "
        f"latest_cache_date={latest_cache_date}"
    )

    fetch_days = min(days, SCAN_FETCH_DAYS) if allow_stale else days

    # 周六日逻辑：有周五缓存直接用；没有周五缓存则抓取到周五并更新
    if weekday >= 5:
        last_friday = _get_last_friday(today)
        if cache_df is not None and latest_cache_date == last_friday:
            _log(f"[KLINE] 周末命中周五缓存，直接返回 code={code}, friday={last_friday}")
            return cache_df

        try:
            _log(f"[KLINE] 周末无周五缓存，尝试抓取周五数据 code={code}, friday={last_friday}")
            stock_df = _fetch_kline_from_baostock(
                code, days=fetch_days, end_date=last_friday, period=period
            )
            stock_df.to_csv(_kline_cache_path(code, period), index=False, encoding='utf8')
            _log(f"[KLINE] 周末抓取周五成功并更新缓存 code={code}, friday={last_friday}")
            return stock_df
        except Exception as e:
            # 周末补抓周五失败时，回退到已有缓存（不要求是周五）
            if cache_df is not None:
                _log(f"周末抓取周五失败，回退已有缓存 {code}: {e}")
                return cache_df
            _log(f"[KLINE] 周末抓取周五失败且无可回退缓存 code={code}, err={e}")
            raise

    # 周一至周五逻辑
    has_today_cache = cache_df is not None and latest_cache_date == today

    # 15:00前：有缓存就先尝试刷新；失败则回退已有缓存（不要求当日缓存）
    if now.hour < CLOSE_HOUR and cache_df is not None and not allow_stale:
        try:
            _log(f"[KLINE] 工作日15点前，有缓存，尝试刷新 code={code}")
            stock_df = _fetch_kline_from_baostock(code, days=fetch_days, end_date=today, period=period)
            stock_df.to_csv(_kline_cache_path(code, period), index=False, encoding='utf8')
            _log(f"[KLINE] 工作日15点前，刷新成功并覆盖缓存 code={code}")
            return stock_df
        except Exception as e:
            _log(f"baostock刷新失败，回退已有缓存 {code}: {e}")
            return cache_df

    # 15:00后：仅当存在“当日缓存”时直接使用
    if now.hour >= CLOSE_HOUR and has_today_cache:
        _log(f"[KLINE] 工作日15点后，命中当日缓存，直接返回 code={code}")
        return cache_df

    # 无.csv缓存或无当日缓存时：按原逻辑抓取并落盘
    _log(f"[KLINE] 走联网抓取并落盘流程 code={code}, reason=无缓存或无当日缓存")
    stock_df = _fetch_kline_from_baostock(code, days=fetch_days, end_date=today, period=period)
    stock_df.to_csv(_kline_cache_path(code, period), index=False, encoding='utf8')
    _log(f"[KLINE] 联网抓取成功并写入缓存 code={code}")
    return stock_df


@api_blueprint.route('/search_stock_index/<stock_input>')
#定义flask接口地址，前端通过 /search_stock_index/代码访问，<stock_input> 是用户输入的股票名 / 代码。
def search_stock_index(stock_input):
    """
    搜索大盘指数或个股的行情数据
    """
    market_type = None
    if stock_input == '上证指数':
        stock = {'code': '000001', 'name': '上证指数'}   #如果是上证指数、中小板指等等，直接给代码；
        market_type = 1
    elif stock_input == '中小板指':
        stock = {'code': '399005', 'name': '中小板指'}
    elif stock_input == '沪深300':
        stock = {'code': '399300', 'name': '沪深300'}
    elif stock_input == '中证1000':
        stock = {'code': '000852', 'name': '中证1000'}
    elif stock_input == '北证50':
        stock = {'code': '899050', 'name': '北证50'}
    else:
        stock = em_spider.stock_index_search(stock_input)  #如果不是大盘指数，调用爬虫匹配股票代码和名称。

    period = _normalize_period(request.args.get('period'))
    pcfg = _PERIOD_CFG[period]

    # 获取该股票历史K线（先查本地缓存，未命中再走baostock并写缓存）
    stock_df = get_kline_with_cache(stock['code'], period=period)

    #.sort_values()是 Pandas 提供的数据排序方法，作用是把表格数据按照某一列进行升序或降序排列。
    # by 表示按照哪一列排序  ascending 表示是否升序 inplace表示直接在原表格上修改
    stock_df.sort_values(by='date', ascending=True, inplace=True)

    for col in ('open', 'close', 'low', 'high', 'volume'):
        stock_df[col] = pd.to_numeric(stock_df[col], errors='coerce')
    stock_df.dropna(subset=['open', 'close', 'low', 'high'], inplace=True)
    top = stock_df[['open', 'close']].max(axis=1)
    bottom = stock_df[['open', 'close']].min(axis=1)
    valid = (stock_df['high'] >= top) & (stock_df['low'] <= bottom) & (stock_df['high'] > 0)
    stock_df = stock_df.loc[valid].copy()
    #kline_data，定义一个变量，用来存放前端可以直接渲染的 K 线数组数据。
    #.values 会把整个表格转换成二维 numpy 数组
    #.tolist()把numpy 数组 转换成 Python 列表（list），前端 JavaScript 只能识别列表，不能识别 Pandas 表格或 numpy 数组
    kline_data = stock_df[['open', 'close', 'low', 'high']].values.tolist()

    close = stock_df['close'].astype(float)

    # 均线与知行指标（参数同通达信缺省：M1=14,M2=28,M3=57,M4=114,M8=120）
    stock_df['MA60'] = tech_util.MA(close, N=60)
    stock_df['MA8'] = tech_util.MA(close, N=120)
    stock_df['ZX_SHORT_TREND'] = tech_util.calc_zhixing_short_trend(close)
    stock_df['ZX_DUOKONG'] = tech_util.calc_zhixing_duokong(close, m1=14, m2=28, m3=57, m4=114)

    kdj = tech_util.calc_kdj(stock_df, N=9, M1=3, M2=3)

    def _indicator_json(series):
        return [
            None if pd.isna(v) else round(float(v), 2)
            for v in series
        ]

    def _line_json(series):
        """折线图用 null 表示空值，避免 '-' 字符串干扰 Y 轴缩放。"""
        return [
            None if pd.isna(v) else round(float(v), 2)
            for v in series
        ]

    dates = stock_df['date'].values.tolist()
    volumes = stock_df['volume'].values.tolist()
    tech_datas = {
        'MA60': _line_json(stock_df['MA60']),
        'MA8': _line_json(stock_df['MA8']),
        'ZX_SHORT_TREND': _line_json(stock_df['ZX_SHORT_TREND']),
        'ZX_DUOKONG': _line_json(stock_df['ZX_DUOKONG']),
        'K': _indicator_json(kdj['K']),
        'D': _indicator_json(kdj['D']),
        'J': _indicator_json(kdj['J']),
    }

    return jsonify({
        'name': '{}({})'.format(stock['name'], stock['code']),
        'period': period,
        'period_label': pcfg['label'],
        'period_name': pcfg['name'],
        'dates': dates,
        'klines': kline_data,
        'volumes': volumes,
        'tech_datas': tech_datas,
    })


@api_blueprint.route('/oamv_kline')
def oamv_kline():
    """指南针活跃市值 0AMV K 线（日/周/月/季）。"""
    period = _normalize_period(request.args.get('period'))
    pcfg = _PERIOD_CFG[period]

    stock_df = compass_oamv.get_oamv_with_cache(period=period)
    stock_df.sort_values(by='date', ascending=True, inplace=True)

    for col in ('open', 'close', 'low', 'high', 'volume'):
        stock_df[col] = pd.to_numeric(stock_df[col], errors='coerce')
    stock_df.dropna(subset=['open', 'close', 'low', 'high'], inplace=True)
    top = stock_df[['open', 'close']].max(axis=1)
    bottom = stock_df[['open', 'close']].min(axis=1)
    valid = (stock_df['high'] >= top) & (stock_df['low'] <= bottom) & (stock_df['high'] > 0)
    stock_df = stock_df.loc[valid].copy()

    kline_data = stock_df[['open', 'close', 'low', 'high']].values.tolist()
    close = stock_df['close'].astype(float)

    stock_df['CYC5'] = tech_util.MA(close, N=5)
    stock_df['CYC13'] = tech_util.MA(close, N=13)
    kdj = tech_util.calc_kdj(stock_df, N=9, M1=3, M2=3)

    def _line_json(series):
        return [None if pd.isna(v) else round(float(v), 2) for v in series]

    def _indicator_json(series):
        return [None if pd.isna(v) else round(float(v), 2) for v in series]

    source_note = '指南针 OAMV'
    if os.environ.get('COMPASS_OAMV_CSV', '').strip():
        source_note = '指南针导出 CSV'

    return jsonify({
        'chart_type': 'oamv',
        'name': '活跃市值(OAMV)',
        'source': source_note,
        'period': period,
        'period_label': pcfg['label'],
        'period_name': pcfg['name'],
        'dates': stock_df['date'].values.tolist(),
        'klines': kline_data,
        'volumes': stock_df['volume'].values.tolist(),
        'tech_datas': {
            'CYC5': _line_json(stock_df['CYC5']),
            'CYC13': _line_json(stock_df['CYC13']),
            'K': _indicator_json(kdj['K']),
            'D': _indicator_json(kdj['D']),
            'J': _indicator_json(kdj['J']),
        },
    })


@api_blueprint.route('/query_jibenmian_info/<stock_input>')
#定义flask接口地址，前端通过/query_jibenmian_info/代码访问
def query_jibenmian_info(stock_input):
    """获取基本面信息"""
    # 调用东方财富爬虫对象 em_spider 的 stock_index_search 方法。
    # 根据用户输入的股票名称 / 代码，匹配出正确的股票代码和股票信息，并把结果存入 stock 变量。
    stock = em_spider.stock_index_search(stock_input)

    #主要指标，经营预测，公司简介，公司名称，分别接收对应的数据，供后面返回给前端。
    #调用爬虫的 get_ji_ben_mian_info 方法，传入股票代码，一次性获取四项基本面数据：
    zyzb_table, jgyc_table, gsjj, gsmc = em_spider.get_ji_ben_mian_info(stock['code'])
    # 获取这支股票对应的所有核心概念板块
    concept_boards = em_spider.get_stock_core_concepts(stock['code'])
    print(concept_boards)
    
    # 概念板块html，定义一个HTML 模板字符串，用于前端直接渲染 “核心概念板块” 表格。
    concept_html = """
    <div class="">
        <div class="card-header">
            <h3>核心概念板块</h3><hr/>
        </div>
        <div class="">
            <table class="table table-hover" style="table-layout:fixed;word-break:break-all;">
            <thead>
                <tr>
                <th scope="col" width="8%">#</th>
                <th scope="col" width="10%">概念板块</th>
                <th scope="col" width="70%">概念解读</th>
                <th scope="col" width="12%">最新涨幅</th>
                </tr>
            </thead>
            <tbody>
                {}
            </tbody>
            </table>
        </div>
        </div>
    """
    trs = ''
    for i, conenpt in enumerate(concept_boards):  #遍历所有概念板块数据：最终所有行都存入 trs 字符串。
        trs += """
        <tr>
            <td>{}</td>
            <td>{}</td>
            <td>{}</td>
            <td style="color: {}">{}%</td>
        </tr>
        """.format(i+1, conenpt['board_name'], conenpt['board_reason'], 'red' if conenpt['board_yield']>0 else 'green' ,conenpt['board_yield'])
    concept_html = concept_html.format(trs)   #把拼接好的所有表格行 trs，填入上面的 HTML 模板中，生成完整的概念板块表格。
        
    return jsonify({
        'zyzb_table': zyzb_table,
        'jgyc_table': jgyc_table,
        'gsjj': gsjj,
        'gsmc': gsmc,
        'concept_boards': concept_html
    })
    

def _parse_recommend_prefs(payload):
    payload = payload or {}
    experience = (payload.get("experience") or "novice").lower()
    style = (payload.get("style") or "conservative").lower()
    if experience not in ("novice", "veteran"):
        experience = "novice"
    if style not in ("conservative", "aggressive"):
        style = "conservative"
    try:
        target_yield = float(payload.get("target_yield") or 10)
    except (TypeError, ValueError):
        target_yield = 10.0
    sector = (payload.get("sector") or "").strip()
    return experience, style, target_yield, sector


def _build_stock_recommend_response(payload):
    """与 /api/stock_recommend 返回结构一致的字典（可直接 jsonify）。"""
    experience, style, target_yield, sector = _parse_recommend_prefs(payload)
    _, df = em_spider.fetch_stock_main_fund_proportion_rank(proxy_url=proxy_url)
    stocks, meta = recommend_util.build_recommendations(
        df, experience, style, target_yield, sector, top_n=10
    )
    if not stocks and meta.get("message"):
        return {
            "success": False,
            "message": meta["message"],
            "stocks": [],
            "meta": meta,
        }
    return {
        "success": True,
        "stocks": stocks,
        "meta": meta,
        "inputs": {
            "experience": experience,
            "style": style,
            "target_yield": target_yield,
            "sector": sector,
        },
        "disclaimer": (
            "本结果为程序根据公开行情与资金数据的规则化排序，不构成任何投资建议；入市需谨慎。"
        ),
    }


@api_blueprint.route('/llm_sector_direction', methods=['POST'])
def llm_sector_direction():
    """
    仅根据本模块 extra 生成大模型板块/行业建议（单独接口，不包含量化选股）。
    JSON: { "extra": "用户在本区输入的说明文字" }
    """
    payload = request.get_json(silent=True) or {}
    extra = payload.get('extra')
    text, err = llm_sector_advice.get_sector_direction_advice(extra)
    if err:
        return jsonify({'success': False, 'message': err, 'content': ''})

    return jsonify({
        'success': True,
        'content': text,
        'disclaimer': (
            '以上内容由大模型根据您在本模块输入的文字生成，仅为板块/行业层面的参考建议，不构成投资建议；请注意甄别与合规风险。'
        ),
    })


@api_blueprint.route('/llm_ten_stocks', methods=['POST'])
def llm_ten_stocks():
    """
    根据本模块输入的自然语言，由大模型生成恰好 10 条 A 股标的（JSON 解析），
    与 /api/stock_recommend 规则量化池无关。
    JSON: { "extra": "用户说明文字" }
    """
    payload = request.get_json(silent=True) or {}
    extra = payload.get('extra')
    stocks, err = llm_sector_advice.get_ten_stocks_recommendation(extra)
    if err:
        return jsonify({
            'success': False,
            'message': err,
            'stocks': [],
            'meta': {'source': 'llm_json'},
        })
    _, rank_df = em_spider.fetch_stock_main_fund_proportion_rank(proxy_url=proxy_url)
    stocks = recommend_util.enrich_llm_stocks_with_main_rank(stocks, rank_df)
    n_enriched = sum(1 for s in stocks if s.get('today_chg') is not None)
    return jsonify({
        'success': True,
        'stocks': stocks,
        'meta': {
            'source': 'llm_json',
            'count': len(stocks),
            'rank_fields_enriched': n_enriched,
        },
        'disclaimer': (
            '以下 10 条由大模型根据您输入的文字生成；'
            '今日涨跌、5日涨跌、5日主力净占比等已尽量与东方财富「主力资金占比」当日排名池按代码对齐，'
            '若某只股票不在该池或字段缺失则仍显示为「—」。不构成投资建议，请自行核实后再决策。'
        ),
    })


@api_blueprint.route('/recommend_sector_list')
def recommend_sector_list():
    """东方财富主力排名中的「所属版块」去重列表，供下拉联想（缓存约 5 分钟）。"""
    now_ts = time.time()
    if (
        now_ts - _RECOMMEND_BOARD_CACHE["ts"] < 300
        and _RECOMMEND_BOARD_CACHE["boards"]
    ):
        return jsonify({"boards": _RECOMMEND_BOARD_CACHE["boards"]})
    _, df = em_spider.fetch_stock_main_fund_proportion_rank(proxy_url=proxy_url)
    if df is None or df.empty:
        boards = [
            "半导体", "银行", "电力设备", "医药生物", "食品饮料", "房地产", "计算机",
            "通信", "有色金属", "汽车", "电子", "机械设备", "传媒", "化工", "公用事业",
            "交通运输", "国防军工", "煤炭", "钢铁", "建筑材料", "农林牧渔",
        ]
    else:
        boards = sorted(df["所属版块"].dropna().astype(str).unique().tolist())
    _RECOMMEND_BOARD_CACHE["ts"] = now_ts
    _RECOMMEND_BOARD_CACHE["boards"] = boards
    return jsonify({"boards": boards})


@api_blueprint.route('/stock_recommend', methods=['POST'])
def stock_recommend():
    """
    根据经验、风格、期望年化、板块偏好推荐 10 只股票（规则打分）。
    JSON: experience novice|veteran, style conservative|aggressive,
          target_yield 数字(期望年化%), sector 板块关键词（子串匹配「所属版块」，可为空或「不限」）
    """
    payload = request.get_json(silent=True) or {}
    return jsonify(_build_stock_recommend_response(payload))


def _api_require_login():
    if not is_login():
        return jsonify({'success': False, 'message': '请先登录'}), 401
    return None


@api_blueprint.route('/quant_strategy/catalog', methods=['GET'])
def quant_strategy_catalog():
    """策略目录 + 当前用户勾选状态。"""
    err = _api_require_login()
    if err:
        return err
    catalog = quant_strategy.list_catalog()
    enabled = quant_strategy_prefs.get_enabled(
        user.login_name,
        default_ids=quant_strategy.default_enabled_ids(),
    )
    try:
        universe_total = len(quant_strategy_scan.get_universe())
    except Exception:
        universe_total = 0
    try:
        kline_cache_count = len([
            f for f in os.listdir(KLINE_CACHE_DIR)
            if f.endswith('.csv') and not any(
                f.endswith(s) for s in ('_w.csv', '_m.csv', '_q.csv')
            )
        ]) if os.path.isdir(KLINE_CACHE_DIR) else 0
    except OSError:
        kline_cache_count = 0
    return jsonify({
        'success': True,
        'catalog': catalog,
        'enabled_ids': enabled,
        'universe_total': universe_total,
        'kline_cache_count': kline_cache_count,
    })


@api_blueprint.route('/quant_strategy/prefs', methods=['GET', 'POST'])
def quant_strategy_prefs_api():
    """读取或保存用户启用的策略 ID 列表。"""
    err = _api_require_login()
    if err:
        return err
    if request.method == 'GET':
        enabled = quant_strategy_prefs.get_enabled(
            user.login_name,
            default_ids=quant_strategy.default_enabled_ids(),
        )
        return jsonify({'success': True, 'enabled_ids': enabled})

    body = request.get_json(silent=True) or {}
    ids = body.get('enabled_ids')
    if not isinstance(ids, list):
        return jsonify({'success': False, 'message': 'enabled_ids 须为数组'}), 400
    valid = {s['id'] for s in quant_strategy.list_catalog()}
    cleaned = [x for x in ids if isinstance(x, str) and x in valid]
    try:
        quant_strategy_prefs.save_enabled(user.login_name, cleaned)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, 'enabled_ids': cleaned})


@api_blueprint.route('/quant_strategy/screen', methods=['POST'])
def quant_strategy_screen():
    """按勾选策略分批扫描全市场个股（多策略 AND）。"""
    err = _api_require_login()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    period = _normalize_period(body.get('period', 'day'))
    pcfg = _PERIOD_CFG[period]

    strategy_ids = body.get('enabled_ids')
    if not isinstance(strategy_ids, list) or not strategy_ids:
        strategy_ids = quant_strategy_prefs.get_enabled(
            user.login_name,
            default_ids=quant_strategy.default_enabled_ids(),
        )

    offset = body.get('offset', 0)
    batch_size = body.get('batch_size', 40)
    cache_only = bool(body.get('cache_only', True))
    workers = body.get('workers', 8)
    result = quant_strategy_scan.screen_batch(
        strategy_ids=strategy_ids,
        period=period,
        offset=offset,
        batch_size=batch_size,
        cache_only=cache_only,
        workers=workers,
    )
    result['period_label'] = pcfg['label']
    result['period_name'] = pcfg['name']
    return jsonify(result)


@api_blueprint.route('/risk/active_amv/today', methods=['GET'])
def risk_active_amv_today_get():
    """读取当前用户今日已保存的活跃市值录入。"""
    err = _api_require_login()
    if err:
        return err
    rec = active_amv_store.get_record(user.login_name)
    if rec is None:
        return jsonify({'success': True, 'has_record': False, 'date': datetime.now().strftime('%Y-%m-%d')})
    return jsonify({'success': True, 'has_record': True, **rec})


@api_blueprint.route('/risk/active_amv/today', methods=['POST'])
def risk_active_amv_today_post():
    """保存今日涨跌幅，并返回风控提示。"""
    err = _api_require_login()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    change_pct = body.get('change_pct')
    if change_pct is None or str(change_pct).strip() == '':
        return jsonify({'success': False, 'message': '请选择涨/跌并填写涨跌幅'}), 400
    try:
        result = active_amv_store.save_today(user.login_name, change_pct)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, **result})