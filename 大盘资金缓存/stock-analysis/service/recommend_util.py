#!/usr/bin/python
# coding=utf-8
"""
根据用户画像（新手/老手、保守/激进、期望年化、板块偏好）在全市场主力排名池中打分，输出推荐列表。
说明：基于公开行情与资金占比的规则化排序，不构成投资建议。
"""
import re

import pandas as pd


def _minmax01(s):
    s = pd.to_numeric(s, errors="coerce")
    if s.dropna().empty:
        return pd.Series(0.5, index=s.index)
    lo, hi = float(s.min()), float(s.max())
    if hi == lo or pd.isna(lo):
        return pd.Series(0.5, index=s.index)
    out = (s - lo) / (hi - lo)
    return out.fillna(0.5)


def _weights(experience, style, target_yield_pct):
    """返回 (w_main, w_mom, w_risk)，对波动项做减法。"""
    t = float(target_yield_pct)
    t = max(3.0, min(t, 50.0))

    if style == "aggressive":
        w_main, w_mom, w_risk = 0.28, 0.52, 0.20
    else:
        w_main, w_mom, w_risk = 0.38, 0.22, 0.40

    if experience == "novice":
        w_mom -= 0.08
        w_risk += 0.08
    else:
        w_mom += 0.05
        w_risk -= 0.05

    if t >= 20:
        w_mom += 0.12
        w_risk -= 0.08
        w_main -= 0.04
    elif t >= 15:
        w_mom += 0.06
        w_risk -= 0.04
        w_main -= 0.02
    elif t <= 6:
        w_mom -= 0.10
        w_risk += 0.08
        w_main += 0.02
    elif t <= 10:
        w_mom -= 0.05
        w_risk += 0.04

    w_main = max(0.05, w_main)
    w_mom = max(0.05, w_mom)
    w_risk = max(0.05, w_risk)
    s = w_main + w_mom + w_risk
    return w_main / s, w_mom / s, w_risk / s


def _assign_star_ratings(items):
    """
    在当次推荐的 10 条结果内，按综合得分相对高低映射为 1～5 星（并列时归一后仍可能同星）。
    """
    if not items:
        return
    raw = [float(x["_score_raw"]) for x in items]
    mn, mx = min(raw), max(raw)
    for x in items:
        if mx - mn < 1e-12:
            n = 3
        else:
            norm = (float(x["_score_raw"]) - mn) / (mx - mn)
            n = max(1, min(5, int(round(1 + norm * 4))))
        x["stars"] = n
        x["stars_display"] = "★" * n + "☆" * (5 - n)
        del x["_score_raw"]


def _score_pool(pool, experience, style, target_yield_pct):
    if pool.empty:
        return pool.assign(_score=pd.Series(dtype=float))

    p = pool.copy()
    main_raw = (
        0.35 * pd.to_numeric(p["今日主力净占比"], errors="coerce").fillna(0)
        + 0.35 * pd.to_numeric(p["5日主力净占比"], errors="coerce").fillna(0)
        + 0.30 * pd.to_numeric(p["10日主力净占比"], errors="coerce").fillna(0)
    )
    mom_raw = (
        0.40 * pd.to_numeric(p["今日涨跌"], errors="coerce").fillna(0)
        + 0.50 * pd.to_numeric(p["5日涨跌"], errors="coerce").fillna(0)
        + 0.10 * pd.to_numeric(p["10日涨跌"], errors="coerce").fillna(0)
    )
    d0 = pd.to_numeric(p["今日涨跌"], errors="coerce").fillna(0)
    d5 = pd.to_numeric(p["5日涨跌"], errors="coerce").fillna(0)
    risk_raw = d0.abs() + 0.5 * d5.abs()

    nm = _minmax01(main_raw)
    nz = _minmax01(mom_raw)
    nr = _minmax01(risk_raw)

    wm, vz, wr = _weights(experience, style, target_yield_pct)
    p["_score"] = wm * nm + vz * nz - wr * nr
    return p


def build_recommendations(
    stock_df, experience, style, target_yield_pct, sector_keyword, top_n=10
):
    if stock_df is None or stock_df.empty:
        return [], {"message": "全市场资金排名数据暂不可用，请稍后重试"}

    df = stock_df.copy()
    df = df[~df["股票名称"].astype(str).str.contains("ST", case=False, na=False)]

    # 排除沪市 B 股等 900 开头的证券代码
    _code = df["股票代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    df = df.loc[~_code.str.startswith("900")].copy()

    if df.empty:
        return [], {"message": "过滤后无可用标的（已排除 ST 股与 900 开头证券代码），请稍后重试"}

    sk = (sector_keyword or "").strip()
    sector_filter_active = bool(sk) and sk != "不限"

    pool_full = df.copy()
    if sector_filter_active:
        mask = df["所属版块"].astype(str).str.contains(sk, case=False, na=False)
        df_sector = df.loc[mask].copy()
    else:
        df_sector = df.copy()

    scored_sector = _score_pool(df_sector, experience, style, target_yield_pct)
    scored_sector = scored_sector.sort_values("_score", ascending=False)

    picked = []
    seen = set()
    for _, row in scored_sector.iterrows():
        c = str(row["股票代码"])
        if c in seen:
            continue
        seen.add(c)
        picked.append((row, True))
        if len(picked) >= top_n:
            break

    if len(picked) < top_n:
        scored_all = _score_pool(pool_full, experience, style, target_yield_pct)
        scored_all = scored_all.sort_values("_score", ascending=False)
        for _, row in scored_all.iterrows():
            c = str(row["股票代码"])
            if c in seen:
                continue
            seen.add(c)
            picked.append((row, False))
            if len(picked) >= top_n:
                break

    out = []
    for rank, (row, in_sector) in enumerate(picked, 1):
        reason = []
        if in_sector and sector_filter_active:
            reason.append("所属板块与所选板块匹配")
        elif sector_filter_active and not in_sector:
            reason.append("板块内候选不足，从全市场按同样偏好补充")
        if style == "conservative":
            reason.append("偏稳健：更重视资金结构与波动控制")
        else:
            reason.append("偏进取：更重视短期动量与资金强度")
        if experience == "novice":
            reason.append("新手向：弱化单日追涨、强化波动惩罚")
        else:
            reason.append("老手向：略提高动量权重")
        reason.append(
            "期望年化约{}%：仅作打分权重微调（历史表现不预示未来）".format(target_yield_pct)
        )

        out.append(
            {
                "rank": rank,
                "code": str(row["股票代码"]),
                "name": str(row["股票名称"]),
                "board": str(row["所属版块"]),
                "_score_raw": float(row["_score"]),
                "today_chg": round(float(row["今日涨跌"]), 2),
                "d5_chg": round(float(row["5日涨跌"]), 2),
                "d10_chg": round(float(row["10日涨跌"]), 2),
                "main_today": round(float(row["今日主力净占比"]), 2),
                "main_d5": round(float(row["5日主力净占比"]), 2),
                "reason": "；".join(reason),
                "sector_matched": bool(in_sector),
            }
        )

    _assign_star_ratings(out)

    meta = {
        "fetched": len(stock_df),
        "after_st_filter": len(df),
        "sector_keyword": sk,
        "sector_filter_active": sector_filter_active,
    }
    return out, meta


def enrich_llm_stocks_with_main_rank(stocks, rank_df):
    """
    用东方财富「主力资金占比排名」池按代码合并，为 LLM 输出的行补齐：
    今日涨跌、5日涨跌、10日涨跌、今日主力净占比、5日主力净占比。
    无法匹配到的股票保持原字段（如 None）。
    """
    def _code6(x):
        s = str(x).strip()
        s = re.sub(r"\.0$", "", s) if s else s
        s = re.sub(r"\D", "", s)
        if len(s) <= 6 and s.isdigit():
            return s.zfill(6)
        return s

    if not stocks or rank_df is None or getattr(rank_df, "empty", True):
        return stocks
    t = rank_df.copy()
    if "股票代码" not in t.columns:
        return stocks
    t["_k"] = t["股票代码"].map(_code6)
    t = t.drop_duplicates(subset=["_k"], keep="first")
    if t.empty:
        return stocks
    try:
        idx = t.set_index("_k")
    except Exception:
        return stocks
    need = ("今日涨跌", "5日涨跌", "今日主力净占比", "5日主力净占比")
    if not all(c in idx.columns for c in need):
        return stocks
    has_d10 = "10日涨跌" in t.columns
    for row in stocks:
        key = _code6(row.get("code"))
        if not key or key not in idx.index:
            continue
        r = idx.loc[key]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        try:
            row["today_chg"] = round(float(r["今日涨跌"]), 2)
            row["d5_chg"] = round(float(r["5日涨跌"]), 2)
            if has_d10:
                row["d10_chg"] = round(float(r["10日涨跌"]), 2)
            row["main_today"] = round(float(r["今日主力净占比"]), 2)
            row["main_d5"] = round(float(r["5日主力净占比"]), 2)
        except (TypeError, ValueError, KeyError):
            continue
    return stocks
