#!/usr/bin/python
# coding=utf-8
"""全市场按量化策略分批选股。"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from service import quant_strategy

_UNIVERSE_CACHE = None


def get_universe():
    global _UNIVERSE_CACHE
    if _UNIVERSE_CACHE is None:
        _UNIVERSE_CACHE = quant_strategy.load_stock_universe()
    return _UNIVERSE_CACHE


def _min_bars_for_strategies(strategy_ids):
    """策略所需最少 K 线根数。"""
    need = 12
    if 'close_gte_zx_duokong' in strategy_ids:
        need = max(need, 114)
    return need


def _row_from_match(item, strategy_ids, details):
    row = {
        'code': item['code'],
        'name': item['name'],
        'strategies': strategy_ids,
        'indicators': details,
    }
    kdj = details.get('kdj_j_lt_13') or {}
    if kdj.get('j') is not None:
        row['j'] = kdj['j']
        row['bar_date'] = kdj.get('date')
    zx = details.get('close_gte_zx_duokong') or {}
    if zx.get('close') is not None:
        row['close'] = zx['close']
        row['zx_duokong'] = zx.get('duokong')
        row['bar_date'] = row.get('bar_date') or zx.get('date')
    return row


def _screen_one(item, strategy_ids, period, cache_only, allow_stale, min_bars):
    code = item['code']
    try:
        df = quant_strategy.prepare_kline_df(
            code,
            period=period,
            cache_only=cache_only,
            allow_stale=allow_stale,
            quiet=True,
        )
        if df.empty:
            return {'kind': 'no_cache' if cache_only else 'skip'}
        if len(df) < min_bars:
            return {'kind': 'skip'}
        ok, details = quant_strategy.check_stock_all_strategies(df, strategy_ids)
        if not ok:
            return {'kind': 'miss'}
        return {'kind': 'match', 'row': _row_from_match(item, strategy_ids, details)}
    except Exception:
        return {'kind': 'error'}


def _aggregate_results(results):
    matches = []
    skipped = 0
    no_cache = 0
    errors = 0
    for r in results:
        kind = r.get('kind')
        if kind == 'match':
            matches.append(r['row'])
        elif kind == 'no_cache':
            no_cache += 1
        elif kind == 'error':
            errors += 1
        else:
            skipped += 1
    return matches, skipped, no_cache, errors


def screen_batch(strategy_ids, period='day', offset=0, batch_size=40, cache_only=False, workers=8):
    """
    扫描 universe[offset : offset+batch_size]。
    返回同时满足全部已选策略的股票（AND）。

    cache_only=True：只读本地 dataset/kline 缓存，不联网（最快）。
    cache_only=False：有缓存直接用；无缓存才联网，且同批次复用 baostock 会话。
    """
    strategy_ids = quant_strategy.validate_strategy_ids(strategy_ids)
    if not strategy_ids:
        return {
            'success': False,
            'message': '请至少选择一项已实现策略',
            'total': 0,
            'offset': offset,
            'batch_size': batch_size,
            'done': True,
            'matches': [],
        }

    universe = get_universe()
    total = len(universe)
    offset = max(0, int(offset))
    max_batch = 200 if cache_only else 80
    batch_size = max(1, min(int(batch_size), max_batch))
    end = min(offset + batch_size, total)
    slice_rows = universe[offset:end]
    min_bars = _min_bars_for_strategies(strategy_ids)
    allow_stale = not cache_only
    workers = max(1, min(int(workers or 8), 16))

    results = []

    if cache_only:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _screen_one, item, strategy_ids, period,
                    cache_only, allow_stale, min_bars,
                )
                for item in slice_rows
            ]
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        from api import baostock_session_begin, baostock_session_end

        baostock_session_begin()
        try:
            for item in slice_rows:
                results.append(
                    _screen_one(item, strategy_ids, period, cache_only, allow_stale, min_bars)
                )
        finally:
            baostock_session_end()

    matches, skipped, no_cache, errors = _aggregate_results(results)
    done = end >= total
    return {
        'success': True,
        'total': total,
        'offset': offset,
        'next_offset': end,
        'batch_size': batch_size,
        'done': done,
        'scanned_in_batch': len(slice_rows),
        'skipped_in_batch': skipped,
        'no_cache_in_batch': no_cache,
        'errors_in_batch': errors,
        'strategy_ids': strategy_ids,
        'period': period,
        'cache_only': cache_only,
        'matches': matches,
        'message': None,
    }
