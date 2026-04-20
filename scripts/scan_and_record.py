#!/usr/bin/env python3
"""
 Scanner + trade_signals 連動模組
 用途：每次掃描結果自動寫入 trade_signals 資料表
      之後可追蹤訊號勝率，強化進化能力

 使用方式：
   python3 scan_and_record.py --scan-type kd_gold_cross
   python3 scan_and_record.py --scan-type macd_bull
   python3 scan_and_record.py --scan-type all
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

# ── Scanner 邏輯（直接內嵌，避免重複import）───────────────────

def get_price_data(stock_id: str, days: int = 120) -> list:
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
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def calc_ma(closes: list, period: int) -> list:
    result = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        result.append(round(sum(closes[i - period + 1 : i + 1]) / period, 2))
    return result


def calc_kd(highs, lows, closes, n=9):
    k = [None] * (n - 1)
    d = [None] * (n - 1)
    rsv_list = []
    for i in range(n - 1, len(closes)):
        wh = max(highs[i - n + 1 : i + 1])
        wl = min(lows[i - n + 1 : i + 1])
        rsv = 50 if wh == wl else (closes[i] - wl) / (wh - wl) * 100
        rsv_list.append(rsv)
    if rsv_list:
        k_val = round(rsv_list[0], 2)
        k.append(k_val)
        d.append(k_val)
        for i in range(1, len(rsv_list)):
            k_val = round((2/3) * k[-1] + (1/3) * rsv_list[i], 2)
            d_val = round((2/3) * d[-1] + (1/3) * k_val, 2)
            k.append(k_val)
            d.append(d_val)
    return k, d


def calc_macd(closes, fast=12, slow=26, signal=9):
    def ema(cols, p):
        k = 2 / (p + 1)
        res = [None] * (p - 1)
        res.append(round(sum(cols[:p]) / p, 4))
        for i in range(p, len(cols)):
            res.append(round(cols[i] * k + res[-1] * (1 - k), 4))
        return res
    ef = ema(closes, fast)
    es = ema(closes, slow)
    dif = [None if ef[i] is None or es[i] is None else round(ef[i] - es[i], 4) for i in range(len(closes))]
    dea = ema([x or 0 for x in dif], signal)
    macd_bar = [None if dif[i] is None or dea[i] is None else round(2 * (dif[i] - dea[i]), 4) for i in range(len(dif))]
    return dif, dea, macd_bar


def get_latest_indicators(stock_id: str):
    """對股票計算最新技術指標"""
    data = get_price_data(stock_id, 120)
    if len(data) < 60:
        return None
    closes = [d["close"] for d in data]
    highs = [d["high"] for d in data]
    lows = [d["low"] for d in data]
    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    k, d = calc_kd(highs, lows, closes)
    dif, dea, macd_bar = calc_macd(closes)
    vol5_ma = calc_ma([d["volume"] for d in data], 5)
    vol20_ma = calc_ma([d["volume"] for d in data], 20)
    return {
        "stock_id": stock_id,
        "date": data[-1]["date"],
        "close": closes[-1],
        "volume": data[-1]["volume"],
        "MA5": _v(ma5), "MA20": _v(ma20), "MA60": _v(ma60),
        "K": _v(k), "D": _v(d),
        "DIF": _v(dif), "DEA": _v(dea), "MACD_Bar": _v(macd_bar),
        "Vol5MA": _v(vol5_ma), "Vol20MA": _v(vol20_ma),
    }


def _v(lst):
    for x in reversed(lst):
        if x is not None:
            return x
    return None


def detect_signals(ind):
    """根據指標判斷訊號"""
    signals = {}
    k, d, dif, dea, macd_bar = ind["K"], ind["D"], ind["DIF"], ind["DEA"], ind["MACD_Bar"]
    ma5, ma20, ma60 = ind["MA5"], ind["MA20"], ind["MA60"]
    close = ind["close"]
    vol, vol5_ma = ind["volume"], ind["Vol5MA"]

    if k is not None and d is not None:
        if k > d and k < 30:
            signals["KD_GOLD_CROSS_LOW"] = "KD低檔黃金交叉"
        elif k > d:
            signals["KD_GOLD_CROSS"] = "KD黃金交叉"
        elif k < d and k > 70:
            signals["KD_DEATH_CROSS_HIGH"] = "KD高檔死亡交叉"
        elif k < d:
            signals["KD_DEATH_CROSS"] = "KD死亡交叉"

    if dif is not None and dea is not None:
        if dif > dea:
            signals["MACD_BULL"] = "MACD多頭"
        else:
            signals["MACD_BEAR"] = "MACD空頭"

    if macd_bar is not None:
        if macd_bar > 0:
            signals["MACD_BAR_POS"] = "MACD柱狀圖正值"
        else:
            signals["MACD_BAR_NEG"] = "MACD柱狀圖負值"

    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            signals["MA_BULL"] = "均線多頭排列"
        elif ma5 < ma20 < ma60:
            signals["MA_BEAR"] = "均線空頭排列"

    if vol5_ma and vol > vol5_ma * 1.8 and close > ma5:
        signals["VOL_SPIKE"] = "量能暴增"

    return signals


def score_signal(ind) -> int:
    """評分：0-10"""
    score = 0
    k, d, dif, dea = ind["K"], ind["D"], ind["DIF"], ind["DEA"]
    ma5, ma20, ma60, close = ind["MA5"], ind["MA20"], ind["MA60"], ind["close"]

    if k and d and k > d: score += 2
    if dif and dea and dif > dea: score += 2
    if ma5 and ma20 and ma60 and ma5 > ma20 > ma60: score += 2
    if close and ma5 and close > ma5: score += 1
    if k and 30 < k < 60: score += 1
    if dif and dea and dif > dea and (dif - dea) > 1: score += 1
    return min(score, 10)


# ── Signals 寫入資料庫 ─────────────────────────────────────

def save_signal(stock_id: str, signal_type: str, direction: str,
                price: float, ind: dict, source: str = "SCANNER"):
    """寫入 trade_signals 表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    indicators_json = json.dumps({
        "MA5": ind.get("MA5"), "MA20": ind.get("MA20"), "MA60": ind.get("MA60"),
        "K": ind.get("K"), "D": ind.get("D"),
        "DIF": ind.get("DIF"), "DEA": ind.get("DEA"), "MACD_Bar": ind.get("MACD_Bar"),
        "RSI": ind.get("RSI"),
        "Vol5MA": ind.get("Vol5MA"), "Vol20MA": ind.get("Vol20MA"),
    }, ensure_ascii=False)

    cursor.execute("""
        INSERT INTO trade_signals
        (stock_id, signal_date, signal_type, signal_source,
         price_at_signal, indicators_json, expected_direction)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (stock_id, ind["date"], signal_type, source,
          price, indicators_json, direction))
    conn.commit()
    conn.close()


# ── 主掃描邏輯 ─────────────────────────────────────────────

SCAN_TYPES = {
    "kd_gold_cross":  {"sig": "KD_GOLD_CROSS_LOW", "dir": "LONG",
                        "filter": lambda s: "KD_GOLD_CROSS_LOW" in s},
    "macd_bull":      {"sig": "MACD_BULL",          "dir": "LONG",
                        "filter": lambda s: s.get("MACD_BULL") and s.get("MACD_BAR_POS")},
    "ma_bull":        {"sig": "MA_BULL",             "dir": "LONG",
                        "filter": lambda s: "MA_BULL" in s},
    "vol_spike":      {"sig": "VOL_SPIKE",           "dir": "LONG",
                        "filter": lambda s: "VOL_SPIKE" in s},
    "all":            None,
}


def run_scan(scan_type: str, dry_run: bool = False) -> list:
    """執行掃描並可選擇寫入 signals"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    results = []
    for sid in stocks:
        ind = get_latest_indicators(sid)
        if not ind:
            continue
        sigs = detect_signals(ind)

        if scan_type != "all":
            cfg = SCAN_TYPES.get(scan_type)
            if not cfg or not cfg["filter"](sigs):
                continue

        # 評分
        score = score_signal(ind)
        if score < 3 and scan_type != "all":
            continue

        # 決定方向
        direction = "LONG"
        if scan_type in ("kd_gold_cross", "macd_bull", "ma_bull", "vol_spike"):
            direction = "LONG"

        results.append({
            "stock_id": sid,
            "close": ind["close"],
            "date": ind["date"],
            "signals": sigs,
            "score": score,
            "direction": direction,
            "indicators": ind,
        })

        if not dry_run:
            for sig_type in sigs.keys():
                save_signal(sid, sig_type, direction, ind["close"], ind)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def print_report(results: list, scan_type: str):
    print(f"\n{'='*55}")
    print(f"🔍 Stephanie 掃描報告 — {scan_type}")
    print(f"{'='*55}")
    if not results:
        print("  （無符合條件的標的）")
        return
    for i, r in enumerate(results[:10], 1):
        sig_list = list(r["signals"].values())
        print(f"\n  {i}. {r['stock_id']}  收{r['close']}  評分{r['score']}/10")
        print(f"     訊號：{' / '.join(sig_list)}")
    print(f"\n{'='*55}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="掃描並記錄交易訊號")
    parser.add_argument("--scan-type", type=str,
                        choices=["kd_gold_cross","macd_bull","ma_bull","vol_spike","all"],
                        default="all")
    parser.add_argument("--dry-run", action="store_true",
                        help="只顯示結果，不寫入資料庫")
    args = parser.parse_args()

    results = run_scan(args.scan_type, dry_run=args.dry_run)
    print_report(results, args.scan_type)

    if not args.dry_run and results:
        print(f"\n✅ 已將 {len(results)} 筆訊號寫入 trade_signals 資料表")
