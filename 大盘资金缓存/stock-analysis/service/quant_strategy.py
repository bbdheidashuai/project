#!/usr/bin/python
# coding=utf-8
"""量化策略：策略注册表 + 个股条件检测。"""
import pandas as pd

from service import tech_util

STOCK_LIST_PATH = 'stock_list.csv'

# 新增策略：在 STRATEGY_CATALOG 登记，并实现 check_xxx(df) 后用 @_register_stock_checker 注册
STRATEGY_CATALOG = [
    {
        'id': 'kdj_j_lt_13',
        'name': 'KDJ J值小于13',
        'description': '个股日线 KDJ(9,3,3) 最新 K 的 J < 13（与个股/大盘 K 线图副图 J 线算法一致）。',
        'default_enabled': True,
        'group': 'KDJ',
        'scope': 'stock',
    },
    {
        'id': 'close_gte_zx_duokong',
        'name': '收盘价≥知行多空线',
        'description': '个股最新一根 K 线收盘价 ≥ 知行多空线（(MA14+MA28+MA57+MA114)/4，与 K 线图一致）。',
        'default_enabled': False,
        'group': '知行',
        'scope': 'stock',
    },
]

STOCK_CHECKERS = {}


def _register_stock_checker(strategy_id):
    def decorator(fn):
        STOCK_CHECKERS[strategy_id] = fn
        return fn
    return decorator


def list_catalog():
    return [dict(item) for item in STRATEGY_CATALOG]


def default_enabled_ids():
    return [s['id'] for s in STRATEGY_CATALOG if s.get('default_enabled')]


def meta(strategy_id):
    for item in STRATEGY_CATALOG:
        if item['id'] == strategy_id:
            return dict(item)
    return None


def norm_code(raw):
    s = str(raw).strip()
    if s.endswith('.0'):
        s = s[:-2]
    if '.' in s:
        return s.split('.')[-1]
    return s


def load_stock_universe():
    """A 股列表（排除 ST、B 股、创业板 300、科创板 688）。"""
    import os

    if not os.path.isfile(STOCK_LIST_PATH):
        from service.stock_spider import EastmoneySpider

        EastmoneySpider().download_stock_list()

    df = pd.read_csv(STOCK_LIST_PATH, encoding='utf-8-sig')
    rows = []
    for _, r in df.iterrows():
        code = norm_code(r.get('code', ''))
        name = str(r.get('code_name', r.get('name', ''))).strip()
        if not code or len(code) != 6 or not code.isdigit():
            continue
        if code.startswith('900'):
            continue
        if code.startswith('300') or code.startswith('688'):
            continue
        if 'ST' in name.upper():
            continue
        rows.append({'code': code, 'name': name})
    return rows


def prepare_kline_df(code, period='day', cache_only=False, allow_stale=False, quiet=False):
    from api import get_kline_with_cache

    raw = get_kline_with_cache(
        code,
        period=period,
        cache_only=cache_only,
        allow_stale=allow_stale,
        quiet=quiet,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    df.sort_values(by='date', inplace=True)
    for col in ('open', 'close', 'low', 'high', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['open', 'close', 'low', 'high'], inplace=True)
    top = df[['open', 'close']].max(axis=1)
    bottom = df[['open', 'close']].min(axis=1)
    valid = (df['high'] >= top) & (df['low'] <= bottom) & (df['high'] > 0)
    return df.loc[valid].copy()


def latest_j_value(df):
    kdj = tech_util.calc_kdj(df, N=9, M1=3, M2=3)
    j_series = kdj['J']
    for i in range(len(j_series) - 1, -1, -1):
        v = j_series.iloc[i]
        if pd.notna(v):
            return float(v), str(df['date'].iloc[i])
    return None, None


@_register_stock_checker('kdj_j_lt_13')
def check_kdj_j_lt_13(df, threshold=13):
    """返回 (是否满足, 指标详情)。"""
    j_val, bar_date = latest_j_value(df)
    if j_val is None:
        return False, {'j': None, 'date': bar_date, 'reason': 'J值尚未形成'}
    return j_val < threshold, {
        'j': round(j_val, 2),
        'date': bar_date,
    }


def latest_close_vs_duokong(df):
    close = df['close'].astype(float)
    duokong = tech_util.calc_zhixing_duokong(close, m1=14, m2=28, m3=57, m4=114)
    for i in range(len(df) - 1, -1, -1):
        c = close.iloc[i]
        d = duokong.iloc[i]
        if pd.notna(c) and pd.notna(d):
            return float(c), float(d), str(df['date'].iloc[i])
    return None, None, None


@_register_stock_checker('close_gte_zx_duokong')
def check_close_gte_zx_duokong(df):
    """最新 K 线收盘价 ≥ 知行多空线。"""
    close_val, duokong_val, bar_date = latest_close_vs_duokong(df)
    if close_val is None or duokong_val is None:
        return False, {
            'close': None,
            'duokong': None,
            'date': bar_date,
            'reason': '知行多空线尚未形成（K 线不足约 114 根）',
        }
    return close_val >= duokong_val, {
        'close': round(close_val, 2),
        'duokong': round(duokong_val, 2),
        'date': bar_date,
    }


def check_stock_all_strategies(df, strategy_ids):
    """单只股票须同时满足所有已选策略（AND）。"""
    details = {}
    for sid in strategy_ids:
        checker = STOCK_CHECKERS.get(sid)
        if checker is None:
            return False, {'_error': f'策略未实现: {sid}'}
        ok, info = checker(df)
        details[sid] = info
        if not ok:
            return False, details
    return True, details


def validate_strategy_ids(strategy_ids):
    valid = {s['id'] for s in STRATEGY_CATALOG}
    return [x for x in (strategy_ids or []) if x in valid and x in STOCK_CHECKERS]
