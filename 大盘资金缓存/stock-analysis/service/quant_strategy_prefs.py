#!/usr/bin/python
# coding=utf-8
"""用户启用的量化策略勾选状态（本地 JSON）。"""
import json
import os

CACHE_PATH = './dataset/quant_strategy/enabled.json'


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


def get_enabled(username, default_ids=None):
    if not username:
        return list(default_ids or [])
    data = _load_all()
    saved = data.get(username)
    if isinstance(saved, list) and saved:
        return saved
    return list(default_ids or [])


def save_enabled(username, strategy_ids):
    if not username:
        raise ValueError('未登录用户')
    if not isinstance(strategy_ids, list):
        raise ValueError('strategy_ids 须为列表')
    data = _load_all()
    data[username] = strategy_ids
    _save_all(data)
    return strategy_ids
