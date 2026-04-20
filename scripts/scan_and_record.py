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

import pandas as pd
import indicators_lib as il

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 股價取得 ────────────────────────────────────────────

def get_price_data(stock_id: str, days: int = 120) -> pd.DataFrame:
    """從資料庫取出近期日K，以 DataFrame 返回"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, open, high, low, close, volume
        FROM daily_price
        WHERE stock_id = ?
        ORDER BY date ASC
        LIMIT ?
    """, (stock_id, days))
    rows = cursor.fetchall()
    conn.close()
    df = pd.DataFrame([dict(r) for r in rows])
    return df


# ── 指標計算 ────────────────────────────────────────────

def get_latest_indicators(stock_id: str):
    """對股票計算最新技術指標，返回 dict"""
    df = get_price_data(stock_id, 120)
    if len(df) < 60:
        return None
    df = il.add_all_indicators(df)
    ind = il.latest_indicators(df)
    ind["stock_id"] = stock_id
    ind["date"] = df["date"].iloc[-1]
    return ind


# ── 訊號判定 ────────────────────────────────────────────

def detect_signals(ind: dict) -> dict:
    """根據指標 dict 判斷訊號"""
    signals = {}
    k, d = ind.get("K"), ind.get("D")
    dif, dea = ind.get("DIF"), ind.get("DEA")
    macd_bar = ind.get("MACD_Bar")
    ma5, ma20, ma60 = ind.get("MA5"), ind.get("MA20"), ind.get("MA60")
    close = ind.get("close")
    vol = ind.get("volume")
    vol5_ma = ind.get("Vol_MA5")

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

    if vol5_ma and vol and close and ma5:
        if vol > vol5_ma * 1.8 and close > ma5:
            signals["VOL_SPIKE"] = "量能暴增"

    return signals


# ── 評分函式 ────────────────────────────────────────────

def score_signal(ind: dict) -> int:
    """評分：0-10"""
    score = 0
    k, d = ind.get("K"), ind.get("D")
    dif, dea = ind.get("DIF"), ind.get("DEA")
    ma5, ma20, ma60 = ind.get("MA5"), ind.get("MA20"), ind.get("MA60")
    close = ind.get("close")

    if k and d and k > d:
        score += 2
    if dif and dea and dif > dea:
        score += 2
    if ma5 and ma20 and ma60 and ma5 > ma20 > ma60:
        score += 2
    if close and ma5 and close > ma5:
        score += 1
    if k and 30 < k < 60:
        score += 1
    if dif and dea and dif > dea and (dif - dea) > 1:
        score += 1
    return min(score, 10)


# ── Signals 寫入資料庫 ───────────────────────────────────

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
        "Vol5MA": ind.get("Vol_MA5"), "Vol20MA": ind.get("Vol_MA20"),
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


# ── 主掃描邏輯 ──────────────────────────────────────────

SCAN_TYPES = {
    "kd_gold_cross": {"sig": "KD_GOLD_CROSS_LOW", "dir": "LONG",
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

        score = score_signal(ind)
        if score < 3 and scan_type != "all":
            continue

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
