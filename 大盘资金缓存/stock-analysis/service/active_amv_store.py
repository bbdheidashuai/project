#!/usr/bin/python
# coding=utf-8
"""量化风控：今日活跃市值手动录入与本地 JSON 缓存。"""
import json
import os
from datetime import datetime

CACHE_PATH = './dataset/risk/active_amv.json'

DEFENSE_THRESHOLD = -2.3   # 跌幅超过 2.3%（涨跌幅 <= -2.3%）
AGGRESSIVE_THRESHOLD = 4.0  # 涨幅超过 4%


def _ensure_dir():
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)


def _load_all():
    _ensure_dir()
    if not os.path.isfile(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data):
    _ensure_dir()
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


def evaluate_advice(change_pct):
    """
    根据涨跌幅返回风控提示。
    change_pct: 百分比数值，如 -2.5 表示跌 2.5%，4.2 表示涨 4.2%。
    """
    if change_pct is None:
        return None, None
    try:
        pct = float(change_pct)
    except (TypeError, ValueError):
        return None, None

    if pct <= DEFENSE_THRESHOLD:
        return 'defense', '近期以稳健防守为主'
    if pct >= AGGRESSIVE_THRESHOLD:
        return 'aggressive', '积极参与主线波段'
    return 'neutral', None


def save_today(username, change_pct, trade_date=None):
    """保存指定用户某交易日的涨跌幅。"""
    if not username:
        raise ValueError('未登录用户')
    try:
        pct = float(change_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError('涨跌幅格式无效') from exc

    day = trade_date or _today_str()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = {
        'change_pct': round(pct, 4),
        'saved_at': now,
    }

    data = _load_all()
    user_bucket = data.setdefault(username, {})
    user_bucket[day] = record
    _save_all(data)

    level, advice = evaluate_advice(pct)
    return {
        'date': day,
        'change_pct': record['change_pct'],
        'saved_at': record['saved_at'],
        'advice_level': level,
        'advice': advice,
    }


def get_record(username, trade_date=None):
    """读取用户某日记录；默认今日。"""
    if not username:
        return None
    day = trade_date or _today_str()
    data = _load_all()
    user_bucket = data.get(username) or {}
    rec = user_bucket.get(day)
    if not rec:
        return None
    level, advice = evaluate_advice(rec.get('change_pct'))
    return {
        'date': day,
        'change_pct': rec.get('change_pct'),
        'saved_at': rec.get('saved_at'),
        'advice_level': level,
        'advice': advice,
    }
