#!/usr/bin/env python3
"""
 Stephanie 量化系統
 技術指標共享函式庫（pure functions）

 每個指標函数：
   - 輸入：股價 pandas.DataFrame（必需欄位：open, high, low, close, volume）
   - 輸出：攜帶指標值的新 DataFrame（不修改原 DataFrame）
   - 指標落後計算，不包含未來函式（可用於回測）

 提供的指標：
   MA, EMA, KD, MACD, RSI, Bollinger Bands, 成交量均量
"""

import pandas as pd
import numpy as np


# ── 工具函式 ────────────────────────────────────────────

def _validate(df: pd.DataFrame) -> pd.DataFrame:
    """確認必要欄位存在並轉為 float"""
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame 缺少必要欄位：{missing}")
    for c in required:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _last_valid(series: pd.Series):
    """取 series 最後一個非 NaN 值，無則回傳 NaN"""
    vals = series.dropna()
    return vals.iloc[-1] if len(vals) else np.nan


# ── 移動平均 MA ─────────────────────────────────────────

def add_ma(df: pd.DataFrame, periods=(5, 10, 20, 60)) -> pd.DataFrame:
    """
    計算多組 MA，附加到 DataFrame。
    參數：
        df      股價 DataFrame
        periods tuple of int，預設 (5, 10, 20, 60)
    返回：
        新 DataFrame（含 MA{period} 欄位）
    """
    df = _validate(df.copy())
    for p in periods:
        col = f"MA{p}"
        if col in df.columns:
            continue
        if len(df) < p:
            # 資料不足，跳過（避免長度 mismatch）
            df[col] = np.nan
            continue
        vals = [np.nan] * (p - 1)
        for i in range(p - 1, len(df)):
            vals.append(round(df["close"].iloc[i - p + 1 : i + 1].mean(), 2))
        df[col] = vals
    return df


# ── 指數移動平均 EMA ─────────────────────────────────────

def _calc_ema_series(series: pd.Series, period: int) -> pd.Series:
    """計算單一 EMA series，不修改原 series"""
    k = 2 / (period + 1)
    ema_vals = [np.nan] * (period - 1)
    # 初始值用 SMA
    init = series.iloc[:period].mean()
    ema_vals.append(init)
    for i in range(period, len(series)):
        ema_vals.append(series.iloc[i] * k + ema_vals[-1] * (1 - k))
    return pd.Series(ema_vals, index=series.index)


def add_ema(df: pd.DataFrame, periods=(12, 26)) -> pd.DataFrame:
    """計算 EMA，附加到 DataFrame"""
    df = _validate(df.copy())
    for p in periods:
        col = f"EMA{p}"
        if col not in df.columns:
            df[col] = _calc_ema_series(df["close"], p).round(4)
    return df


# ── KD 隨機指標 ─────────────────────────────────────────

def add_kd(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """
    計算 KD 指標，附加 K、D 欄位。
    K、D 初始值 = 第一個 RSV
    """
    df = _validate(df.copy())
    rsv = [np.nan] * (n - 1)
    for i in range(n - 1, len(df)):
        wh = df["high"].iloc[i - n + 1 : i + 1].max()
        wl = df["low"].iloc[i - n + 1 : i + 1].min()
        rsv.append(50.0 if wh == wl else (df["close"].iloc[i] - wl) / (wh - wl) * 100)

    rsv_s = pd.Series(rsv, index=df.index)
    k = [np.nan] * (n - 1)
    d = [np.nan] * (n - 1)

    # 用 list 滾動計算以保持效率
    k_list = list(k)
    d_list = list(d)

    # 第一個有效 RSV
    # Standard KD initialization: start at 50
    first_rsv = 50.0
    k_list.append(first_rsv)
    d_list.append(first_rsv)

    for i in range(n, len(rsv_s)):
        if pd.isna(rsv_s.iloc[i]):
            k_list.append(np.nan)
            d_list.append(np.nan)
        else:
            k_val = (2 / 3) * k_list[-1] + (1 / 3) * rsv_s.iloc[i]
            d_val = (2 / 3) * d_list[-1] + (1 / 3) * k_val
            k_list.append(k_val)
            d_list.append(d_val)

    df["K"] = pd.Series(k_list, index=df.index).round(2)
    df["D"] = pd.Series(d_list, index=df.index).round(2)
    return df


# ── MACD ────────────────────────────────────────────────

def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    計算 MACD（DIF, DEA, MACD_Bar），附加到 DataFrame。
    DIF  = EMA(fast) - EMA(slow)
    DEA  = EMA(DIF, signal)
    Bar  = 2 * (DIF - DEA)
    """
    df = _validate(df.copy())
    ef = _calc_ema_series(df["close"], fast)
    es = _calc_ema_series(df["close"], slow)
    dif = (ef - es).round(4)

    # DEA 用 None→0 的 DIF series 計算
    dif_for_dea = dif.fillna(0)
    dea = _calc_ema_series(dif_for_dea, signal).round(4)

    df["DIF"] = dif
    df["DEA"] = dea
    df["MACD_Bar"] = (2 * (dif - dea)).round(4)
    return df


# ── RSI ────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    計算 RSI（SMA 平滑版），附加 RSI 欄位。
    """
    df = _validate(df.copy())
    diffs = df["close"].diff()

    gains = diffs.clip(lower=0)
    losses = (-diffs.clip(upper=0))

    avg_gain = gains.iloc[:period].mean()
    avg_loss = losses.iloc[:period].mean()

    rsi_vals = [np.nan] * period

    for i in range(period, len(df)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(round(100 - 100 / (1 + rs), 2))

    df["RSI"] = pd.Series(rsi_vals, index=df.index)
    return df


# ── Bollinger Bands ──────────────────────────────────────

def add_bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2) -> pd.DataFrame:
    """
    計算布林帶，附加 BB_Upper、BB_MA、BB_Lower 欄位。
    BB_MA    = MA(period)
    BB_Upper = MA + std_mult * STD
    BB_Lower = MA - std_mult * STD
    """
    df = _validate(df.copy())

    ma = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()

    df["BB_Upper"] = (ma + std_mult * std).round(2)
    df["BB_MA"] = ma.round(2)
    df["BB_Lower"] = (ma - std_mult * std).round(2)
    return df


# ── 成交量均量 ──────────────────────────────────────────

def add_volume_ma(df: pd.DataFrame, periods=(5, 20)) -> pd.DataFrame:
    """
    計算成交量均量，附加 Vol_MA{period} 欄位。
    """
    df = _validate(df.copy())
    for p in periods:
        col = f"Vol_MA{p}"
        if col not in df.columns:
            df[col] = df["volume"].rolling(window=p).mean()
    return df


# ── 一鍵加載所有指標 ────────────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    對輸入的股價 DataFrame 添加所有指標。
    依照依賴順序執行（MA/EMA → KD/MACD/RSI/BB → VolMA）。
    """
    df = add_ma(df)
    df = add_ema(df)
    df = add_kd(df)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_bollinger(df)
    df = add_volume_ma(df)
    return df


# ── 取得最新指標值（dict 格式）───────────────────────────

def latest_indicators(df: pd.DataFrame) -> dict:
    """
    取最後一筆（非 NaN）指標值，以 dict 回傳。
    df 需已透過 add_all_indicators 添加指標。
    """
    result = {}
    for col in df.columns:
        if col in ("open", "high", "low", "close", "volume"):
            result[col] = df[col].iloc[-1]
        else:
            result[col] = _last_valid(df[col])
    return result


# ── 指標落後取值（落後 N 筆的數值）───────────────────────

def lag_indicators(df: pd.DataFrame, n: int = 1) -> pd.DataFrame:
    """
    取落後 n 筆的指標值（用於避免偷價）。
    返回的 DataFrame 第 i 列 = 原始第 i-n 列的指標。
    第 0~(n-1) 列為 NaN。
    """
    return df.shift(n)


# ── 純量取最新 non-NaN 值 ────────────────────────────────

def get_valid(val):
    """從 series 末尾或純量取第一個非 NaN 值，無則回傳 None"""
    if isinstance(val, pd.Series):
        vals = val.dropna()
        return float(vals.iloc[-1]) if len(vals) else None
    elif isinstance(val, (int, float)):
        return None if (val is None or np.isnan(val)) else float(val)
    return None
