#!/usr/bin/env python3
"""
 Stephanie 量化系統
 技術指標計算引擎（無需talib，純Python實現）
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 工具函式 ────────────────────────────────────────────

def get_price_data(stock_id: str, days: int = 120) -> list:
    """從資料庫取出近期日K"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM daily_price
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, days))
    rows = cursor.fetchall()
    conn.close()
    # 轉成 [dict]，並翻轉成由舊到新（方便指標計算）
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def calc_ma(closes: list, period: int) -> list:
    """移動平均線（MA）"""
    result = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        ma = sum(closes[i - period + 1 : i + 1]) / period
        result.append(round(ma, 2))
    return result


def calc_ema(closes: list, period: int) -> list:
    """指數移動平均（EMA）"""
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    ema = sum(closes[:period]) / period
    result.append(round(ema, 2))
    for i in range(period, len(closes)):
        ema = closes[i] * k + ema * (1 - k)
        result.append(round(ema, 2))
    return result


def calc_kd(highs: list, lows: list, closes: list, n: int = 9) -> tuple:
    """
    KD 指標（預設 N=9）
    返回 (K_series, D_series)
    """
    k = [None] * (n - 1)
    d = [None] * (n - 1)

    rsv_list = []
    for i in range(n - 1, len(closes)):
        window_high = max(highs[i - n + 1 : i + 1])
        window_low = min(lows[i - n + 1 : i + 1])
        if window_high == window_low:
            rsv = 50
        else:
            rsv = (closes[i] - window_low) / (window_high - window_low) * 100
        rsv_list.append(rsv)

    # 初始化K、D
    if rsv_list:
        k.append(round(rsv_list[0], 2))
        d.append(round(rsv_list[0], 2))

        for i in range(1, len(rsv_list)):
            k_val = (2 / 3) * k[-1] + (1 / 3) * rsv_list[i]
            d_val = (2 / 3) * d[-1] + (1 / 3) * k_val
            k.append(round(k_val, 2))
            d.append(round(d_val, 2))

    return k, d


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """
    MACD 指標
    返回 (DIF, DEA, MACD_Bar)
    """
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)

    dif = []
    for i in range(len(closes)):
        if ema_fast[i] is None or ema_slow[i] is None:
            dif.append(None)
        else:
            dif.append(round(ema_fast[i] - ema_slow[i], 4))

    dea = calc_ema([x if x is not None else 0 for x in dif], signal)

    macd_bar = []
    for i in range(len(dif)):
        if dif[i] is None or dea[i] is None:
            macd_bar.append(None)
        else:
            macd_bar.append(round(2 * (dif[i] - dea[i]), 4))

    return dif, dea, macd_bar


def calc_rsi(closes: list, period: int = 14) -> list:
    """RSI 指標（SMA版）"""
    result = [None] * period
    if len(closes) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = round(100 - (100 / (1 + rs)), 2)

        result.append(rsi)

    return result


def calc_bollinger(closes: list, period: int = 20, std_mult: float = 2) -> tuple:
    """布林帶（中軌=MA，帶寬=2*STD）"""
    ma = calc_ma(closes, period)
    upper = []
    lower = []
    for i in range(len(closes)):
        if ma[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            std = (sum((x - ma[i]) ** 2 for x in window) / period) ** 0.5
            upper.append(round(ma[i] + std_mult * std, 2))
            lower.append(round(ma[i] - std_mult * std, 2))
    return upper, ma, lower


# ── 訊號產生器 ─────────────────────────────────────────

def generate_signals(stock_id: str, days: int = 120) -> dict:
    """
    對指定股票產生完整技術分析結果
    返回所有指標數值與訊號狀態
    """
    data = get_price_data(stock_id, days)
    if len(data) < 60:
        return {"error": f"資料不足（僅{len(data)}筆），需要至少60筆"}

    closes = [d["close"] for d in data]
    highs = [d["high"] for d in data]
    lows = [d["low"] for d in data]
    volumes = [d["volume"] for d in data]
    dates = [d["date"] for d in data]

    # 計算各項指標
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    k, d = calc_kd(highs, lows, closes)
    dif, dea, macd_bar = calc_macd(closes)
    rsi = calc_rsi(closes)
    bb_upper, bb_ma, bb_lower = calc_bollinger(closes)

    # 最近N筆（最新收盤）
    n = -1  # 最新

    # 均量
    vol5_ma = calc_ma(volumes, 5)
    vol20_ma = calc_ma(volumes, 20)

    # 找最近的有效值
    def get_valid(datas, idx=n):
        for i in range(len(datas) - 1, -1, -1):
            if datas[i] is not None:
                return datas[i]
        return None

    result = {
        "stock_id": stock_id,
        "analyzed_date": dates[n],
        "close": closes[n],
        "volume": volumes[n],
        "indicators": {
            "MA5": get_valid(ma5),
            "MA20": get_valid(ma20),
            "MA60": get_valid(ma60),
            "K": get_valid(k),
            "D": get_valid(d),
            "DIF": get_valid(dif),
            "DEA": get_valid(dea),
            "MACD_Bar": get_valid(macd_bar),
            "RSI": get_valid(rsi),
            "BB_Upper": get_valid(bb_upper),
            "BB_MA": get_valid(bb_ma),
            "BB_Lower": get_valid(bb_lower),
            "Vol_5MA": get_valid(vol5_ma),
            "Vol_20MA": get_valid(vol20_ma),
        },
        "signals": {},
        "notes": [],
    }

    # ── 訊號判定 ──────────────────────────────────────

    signals = {}

    # KD
    k_val = get_valid(k)
    d_val = get_valid(d)
    if k_val is not None and d_val is not None:
        if k_val > d_val and k_val < 30:
            signals["KD_LowGoldCross"] = "🟢 低檔黃金交叉（初步買點）"
        elif k_val > d_val:
            signals["KD_GoldCross"] = "🟢 黃金交叉（多頭）"
        elif k_val < d_val and k_val > 70:
            signals["KD_DeathCross"] = "🔴 高檔死亡交叉（警訊）"
        elif k_val < d_val:
            signals["KD_DeathCross"] = "🔴 死亡交叉（空頭）"

    # MACD
    dif_v = get_valid(dif)
    dea_v = get_valid(dea)
    macd_v = get_valid(macd_bar)
    if dif_v is not None and dea_v is not None:
        if dif_v > dea_v:
            signals["MACD_Bull"] = "🟢 DIF > DEA（多頭）"
        else:
            signals["MACD_Bear"] = "🔴 DIF < DEA（空頭）"
    if macd_v is not None:
        if macd_v > 0:
            signals["MACD_BarPos"] = "🟢 MACD 柱狀圖正值"
        else:
            signals["MACD_BarNeg"] = "🔴 MACD 柱狀圖負值"

    # RSI
    rsi_v = get_valid(rsi)
    if rsi_v is not None:
        if rsi_v > 70:
            signals["RSI_Overbought"] = f"⚠️ RSI 超買：{rsi_v:.1f}"
        elif rsi_v < 30:
            signals["RSI_Oversold"] = f"🟢 RSI 超賣：{rsi_v:.1f}"

    # 均線多頭排列
    ma5_v = get_valid(ma5)
    ma20_v = get_valid(ma20)
    ma60_v = get_valid(ma60)
    if all(x is not None for x in [ma5_v, ma20_v, ma60_v]):
        if ma5_v > ma20_v > ma60_v:
            signals["MA_Bull"] = "🟢 均線多頭排列（5>20>60）"
        elif ma5_v < ma20_v < ma60_v:
            signals["MA_Bear"] = "🔴 均線空頭排列"

    # 量價結構
    close_v = closes[n]
    vol_v = volumes[n]
    vol5_ma_v = get_valid(vol5_ma)
    vol20_ma_v = get_valid(vol20_ma)
    if vol5_ma_v and vol20_ma_v:
        if vol_v > vol5_ma_v * 1.5 and close_v > get_valid(ma5):
            signals["VolPrice_Bull"] = "🟢 價漲量增（動能確認）"
        elif vol_v < vol5_ma_v * 0.5:
            signals["VolPrice_Weak"] = "⚠️ 量縮（觀望）"

    # 內盤/外盤比（若未來串進即時行情，可在此對比）

    result["signals"] = signals

    # ── 綜合評分 ──────────────────────────────────────
    score = 0
    if k_val and d_val and k_val > d_val:
        score += 2
    if dif_v and dea_v and dif_v > dea_v:
        score += 2
    if rsi_v and 40 < rsi_v < 70:
        score += 1
    elif rsi_v and rsi_v < 30:
        score += 2
    if ma5_v and ma20_v and ma60_v and ma5_v > ma20_v > ma60_v:
        score += 2
    if close_v > ma5_v:
        score += 1

    result["score"] = min(score, 10)  # 最高10分
    result["score_label"] = (
        "強力買進" if score >= 7
        else "偏多" if score >= 5
        else "中立" if score >= 3
        else "偏空"
    )

    return result


def print_report(stock_id: str = "4967"):
    """產出文字版技術分析報告"""
    r = generate_signals(stock_id)
    if "error" in r:
        print(r["error"])
        return

    print(f"\n{'='*50}")
    print(f"【Stephanie 技術分析報告】{r['stock_id']}")
    print(f"分析日期：{r['analyzed_date']}")
    print(f"最新收盤：{r['close']} /成交量：{r['volume']:,}")
    print(f"{'='*50}")
    print(f"\n▍技術指標數值")
    ind = r["indicators"]
    print(f"  MA5/20/60 : {ind['MA5']} / {ind['MA20']} / {ind['MA60']}")
    print(f"  K/D       : {ind['K']} / {ind['D']}")
    print(f"  DIF/DEA   : {ind['DIF']} / {ind['DEA']}")
    print(f"  MACD_Bar  : {ind['MACD_Bar']}")
    print(f"  RSI(14)   : {ind['RSI']}")
    print(f"  布林帶    : {ind['BB_Lower']} ～ {ind['BB_MA']} ～ {ind['BB_Upper']}")
    print(f"  均量5/20  : {ind['Vol_5MA']:,.0f} / {ind['Vol_20MA']:,.0f}")

    print(f"\n▍訊號判定")
    for sig, desc in r["signals"].items():
        print(f"  {desc}")

    print(f"\n▍綜合評分：{r['score']}/10 — {r['score_label']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "4967"
    print_report(stock)
