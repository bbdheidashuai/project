#!/usr/bin/python
# coding=utf-8
import pandas as pd
import numpy as np


def AVEDEV(seq: pd.Series, N):
    """
    平均绝对偏差 mean absolute deviation

    之前用mad的计算模式依然返回的是单值
    """
    return seq.rolling(N).apply(lambda x: (np.abs(x - x.mean())).mean(), raw=True)


def MA(seq: pd.Series, N):
    return seq.rolling(N).mean()


def SMA(seq: pd.Series, N, M=1):
    """
    威廉SMA算法
    https://www.joinquant.com/post/867
    """
    if not isinstance(seq, pd.Series):
        seq = pd.Series(seq)
    ret = []
    i = 1
    length = len(seq)
    # 跳过X中前面几个 nan 值
    while i < length:
        if np.isnan(seq.iloc[i]):
            i += 1
        else:
            break
    preY = seq.iloc[i]  # Y'
    ret.append(preY)
    while i < length:
        Y = (M * seq.iloc[i] + (N - M) * preY) / float(N)
        ret.append(Y)
        preY = Y
        i += 1
    return pd.Series(ret, index=seq.tail(len(ret)).index)


def SMA_tdx(seq: pd.Series, N: int, M: int = 1) -> pd.Series:
    """
    通达信 SMA(X, N, M)：Y = (M*X + (N-M)*Y') / N，与序列等长，无效区间为 nan。
    """
    if not isinstance(seq, pd.Series):
        seq = pd.Series(seq, dtype=float)
    out = np.full(len(seq), np.nan, dtype=float)
    arr = seq.astype(float).values
    start = 0
    while start < len(arr) and np.isnan(arr[start]):
        start += 1
    if start >= len(arr):
        return pd.Series(out, index=seq.index)
    y = float(arr[start])
    out[start] = y
    for i in range(start + 1, len(arr)):
        if np.isnan(arr[i]):
            out[i] = y
            continue
        y = (M * float(arr[i]) + (N - M) * y) / float(N)
        out[i] = y
    return pd.Series(out, index=seq.index)


def calc_kdj(df, N=9, M1=3, M2=3):
    """
    通达信 KDJ（缺省 N=9, M1=3, M2=3）：
    RSV=(CLOSE-LLV(LOW,N))/(HHV(HIGH,N)-LLV(LOW,N))*100
    K=SMA(RSV,M1,1); D=SMA(K,M2,1); J=3*K-2*D
    """
    low = df['low'].astype(float)
    high = df['high'].astype(float)
    close = df['close'].astype(float)
    llv = low.rolling(N, min_periods=N).min()
    hhv = high.rolling(N, min_periods=N).max()
    denom = (hhv - llv).replace(0, np.nan)
    rsv = (close - llv) / denom * 100.0
    k = SMA_tdx(rsv, M1, 1)
    d = SMA_tdx(k, M2, 1)
    j = 3 * k - 2 * d
    return {
        'K': k,
        'D': d,
        'J': j,
    }


def EMA(seq: pd.Series, N):
    return seq.ewm(span=N, min_periods=N - 1, adjust=True).mean()


def EMA_tdx(seq: pd.Series, N: int) -> pd.Series:
    """通达信 EMA：Y = 2/(N+1)*X + (N-1)/(N+1)*Y'"""
    close = seq.astype(float)
    return close.ewm(alpha=2.0 / (N + 1), adjust=False).mean()


def calc_zhixing_short_trend(close: pd.Series) -> pd.Series:
    """知行短期趋势线: EMA(EMA(C,10),10)"""
    return EMA_tdx(EMA_tdx(close, 10), 10)


def calc_zhixing_duokong(close: pd.Series, m1=14, m2=28, m3=57, m4=114) -> pd.Series:
    """知行多空线: (MA(C,M1)+MA(C,M2)+MA(C,M3)+MA(C,M4))/4"""
    return (
        MA(close, m1) + MA(close, m2) + MA(close, m3) + MA(close, m4)
    ) / 4.0


def MACD(CLOSE, short=12, long=26, mid=9):
    """
    MACD CALC
    """
    DIF = EMA(CLOSE, short) - EMA(CLOSE, long)
    DEA = EMA(DIF, mid)
    MACD = (DIF - DEA) * 2
    return {
        'DIF': DIF.fillna(0).to_list(),
        'DEA': DEA.fillna(0).to_list(),
        'MACD': MACD.fillna(0).to_list()
    }