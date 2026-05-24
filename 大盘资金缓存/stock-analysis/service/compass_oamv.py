#!/usr/bin/python
# coding=utf-8
"""
指南针活跃市值指数 0AMV（OAMV）K 线数据。

数据来源优先级：
1. 环境变量 COMPASS_OAMV_CSV 指向的导出文件
2. 本地缓存 dataset/oamv/0AMV*.csv
3. 按指南针公开换算思路：两市成交额 SMA(10,1) / 1e7 推算（与软件内曲线接近，非官方接口）
"""
import os
from datetime import datetime, timedelta

import baostock as bs
import pandas as pd

from service import tech_util

OAMV_CODE = '0AMV'
OAMV_CACHE_DIR = './dataset/oamv'
OAMV_DIVISOR = 1e7  # 通达信换算：SMA(AMOUNT,10,1)/10000000

_PERIOD_CFG = {
    'day': {'suffix': '', 'baostock_freq': 'd', 'fetch_days': 1200},
    'week': {'suffix': '_w', 'baostock_freq': 'w', 'fetch_days': 1200 * 7},
    'month': {'suffix': '_m', 'baostock_freq': 'm', 'fetch_days': 1200 * 31},
    'quarter': {'suffix': '_q', 'baostock_freq': 'd', 'fetch_days': 1200 * 7, 'resample': 'quarter'},
}


def _normalize_period(period):
    p = (period or 'day').lower().strip()
    return p if p in _PERIOD_CFG else 'day'


def _cache_path(period='day'):
    os.makedirs(OAMV_CACHE_DIR, exist_ok=True)
    suffix = _PERIOD_CFG[_normalize_period(period)]['suffix']
    return os.path.join(OAMV_CACHE_DIR, f'{OAMV_CODE}{suffix}.csv')


def _read_cache(period='day'):
    path = _cache_path(period)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, encoding='utf8')
    except Exception:
        return None
    required = {'date', 'open', 'close', 'high', 'low', 'volume'}
    if df.empty or not required.issubset(df.columns):
        return None
    for col in ['open', 'close', 'high', 'low', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['date', 'open', 'close', 'high', 'low'], inplace=True)
    return df if not df.empty else None


def _latest_date(df):
    if df is None or df.empty:
        return None
    dates = pd.to_datetime(df['date'], errors='coerce').dropna()
    return None if dates.empty else dates.max().date()


def _resample_quarter(df):
    tmp = df.copy()
    tmp['date'] = pd.to_datetime(tmp['date'], errors='coerce')
    tmp.dropna(subset=['date'], inplace=True)
    tmp.sort_values('date', inplace=True)
    tmp.set_index('date', inplace=True)
    agg = tmp.resample('QE').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    agg = agg.reset_index()
    agg['date'] = agg['date'].dt.strftime('%Y-%m-%d')
    return agg[['date', 'open', 'close', 'low', 'high', 'volume']]


def _build_ohlc_from_close(close: pd.Series):
    """由 OAMV 收盘价序列生成 OHLC。"""
    close = close.astype(float)
    open_ = close.shift(1)
    if len(open_) > 0:
        open_.iloc[0] = close.iloc[0]
    frame = pd.concat([open_, close], axis=1)
    high = frame.max(axis=1) * 1.0006
    low = frame.min(axis=1) * 0.9994
    return open_, high, low, close


def _amount_series_from_baostock(period, end_date, days):
    """拉取上证+深证成交额并合并。"""
    cfg = _PERIOD_CFG[_normalize_period(period)]
    end_dt = end_date if end_date is not None else datetime.now().date()
    start_date = (end_dt - timedelta(days=days)).strftime('%Y-%m-%d')
    end_str = end_dt.strftime('%Y-%m-%d')
    fields = 'date,open,high,low,close,volume,amount'

    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f'baostock 登录失败: {lg.error_msg}')
    try:
        frames = []
        for bs_code in ('sh.000001', 'sz.399001'):
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields,
                start_date=start_date,
                end_date=end_str,
                frequency=cfg['baostock_freq'],
                adjustflag='3',
            )
            if rs.error_code != '0':
                raise RuntimeError(f'查询 {bs_code} 失败: {rs.error_msg}')
            part = rs.get_data()
            if part.empty:
                continue
            part['amount'] = pd.to_numeric(part['amount'], errors='coerce')
            part = part[['date', 'amount']].rename(columns={'amount': bs_code})
            frames.append(part)

        if len(frames) < 2:
            raise RuntimeError('未获取到上证/深证成交额')

        merged = frames[0]
        for part in frames[1:]:
            merged = pd.merge(merged, part, on='date', how='outer')
        merged.sort_values('date', inplace=True)
        merged.fillna(0, inplace=True)
        merged['total_amount'] = merged['sh.000001'] + merged['sz.399001']
        return merged[['date', 'total_amount']]
    finally:
        bs.logout()


def _compute_oamv_df(amount_df: pd.DataFrame):
    """
    指南针 0AMV 常用换算：SMA(两市成交额, 10, 1) / 1e7
    并生成 K 线 OHLC；成交量用成交额（亿元）便于副图展示。
    """
    df = amount_df.copy()
    df['total_amount'] = pd.to_numeric(df['total_amount'], errors='coerce')
    df.dropna(subset=['total_amount'], inplace=True)
    df.sort_values('date', inplace=True)

    raw = df['total_amount'].astype(float)
    close = tech_util.SMA_tdx(raw, 10, 1) / OAMV_DIVISOR
    open_, high, low, close = _build_ohlc_from_close(close)
    volume = (raw / 1e8).round(4)  # 亿元

    out = pd.DataFrame({
        'date': df['date'].values,
        'open': open_.values,
        'high': high.values,
        'low': low.values,
        'close': close.values,
        'volume': volume.values,
    })
    out.dropna(subset=['close'], inplace=True)
    return out


def _load_external_csv():
    path = os.environ.get('COMPASS_OAMV_CSV', '').strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path, encoding='utf8')
    except Exception:
        try:
            df = pd.read_csv(path, encoding='gbk')
        except Exception:
            return None
    required = {'date', 'open', 'close', 'high', 'low'}
    if not required.issubset(df.columns):
        return None
    if 'volume' not in df.columns:
        df['volume'] = 0
    return df[list(required) + ['volume']]


def _fetch_oamv(period='day', end_date=None):
    period = _normalize_period(period)
    cfg = _PERIOD_CFG[period]
    days = cfg['fetch_days']

    external = _load_external_csv()
    if external is not None:
        df = external.copy()
    else:
        amount_df = _amount_series_from_baostock(period, end_date, days)
        df = _compute_oamv_df(amount_df)

    if cfg.get('resample') == 'quarter':
        df = _resample_quarter(df)

    df.sort_values('date', inplace=True)
    return df


def get_oamv_with_cache(period='day'):
    period = _normalize_period(period)
    cache_df = _read_cache(period)
    today = datetime.now().date()
    latest = _latest_date(cache_df)

    if cache_df is not None and latest == today:
        return cache_df

    if cache_df is not None and latest is not None and today.weekday() >= 5:
        return cache_df

    try:
        stock_df = _fetch_oamv(period=period, end_date=today)
    except Exception as exc:
        if cache_df is not None:
            print(f'[OAMV] 联网失败，使用缓存: {exc}')
            return cache_df
        raise

    if stock_df.empty:
        if cache_df is not None:
            return cache_df
        raise RuntimeError('OAMV 数据为空')

    stock_df.to_csv(_cache_path(period), index=False, encoding='utf8')
    return stock_df
