#!/usr/bin/env python3
"""
 Scanner + trade_signals 連動模組
 用途：每次掃描結果自動寫入 trade_signals 資料表
      之後可追蹤訊號勝率，強化進化能力

 效能優化：
  - 只掃描 watchlist 白名單（不再全資料庫掃描）
  - 指標從 indicator_cache 讀取（不重複計算）
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
from scanner import (
    get_watchlist_stocks,
    get_indicators,
    detect_signals,
    get_cached_indicators,
)

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 評分 ────────────────────────────────────────────────

def score_signal(ind: dict) -> int:
    """評分：0-10"""
    score = 0
    k, d = ind.get("K"), ind.get("D")
    dif, dea = ind.get("DIF"), ind.get("DEA")
    ma5, ma20, ma60 = ind.get("MA5"), ind.get("MA20"), ind.get("MA60")
    close = ind.get("close")

    if k and d and k > d:
        score += 2
    if dif is not None and dea is not None and dif > dea:
        score += 2
    if ma5 and ma20 and ma60 and ma5 > ma20 > ma60:
        score += 2
    if close and ma5 and close > ma5:
        score += 1
    if k and 30 < k < 60:
        score += 1
    if dif is not None and dea is not None and dif > dea and (dif - dea) > 1:
        score += 1
    return min(score, 10)


# ── Signals 寫入 ───────────────────────────────────────

def save_signal(stock_id: str, signal_type: str, direction: str,
                price: float, ind: dict, market: str = "TW",
                source: str = "SCANNER"):
    """寫入 trade_signals 表"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    indicators_json = json.dumps({
        "MA5": ind.get("MA5"), "MA20": ind.get("MA20"), "MA60": ind.get("MA60"),
        "K": ind.get("K"), "D": ind.get("D"),
        "DIF": ind.get("DIF"), "DEA": ind.get("DEA"), "MACD_Bar": ind.get("MACD_Bar"),
        "RSI": ind.get("RSI"),
        "Vol_MA5": ind.get("Vol_MA5"), "Vol_MA20": ind.get("Vol_MA20"),
        "close": ind.get("close"),
        "date": ind.get("date"),
    }, ensure_ascii=False)

    cur.execute("""
        INSERT INTO trade_signals
        (stock_id, signal_date, signal_type, signal_source, market,
         price_at_signal, indicators_json, expected_direction)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (stock_id, ind["date"], signal_type, source, market,
          price, indicators_json, direction))
    conn.commit()
    conn.close()


# ── 主掃描邏輯（白名單 + 快取）────────────────────────────

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


def run_scan(scan_type: str = "all", market: str = "TW",
             dry_run: bool = False) -> list:
    """
    執行掃描（白名單版）
    - 從 watchlist 取股票
    - 從 indicator_cache 取指標（快取優先）
    - 寫入 trade_signals（可選）
    """
    watchlist = get_watchlist_stocks(market)
    results = []

    for sid, name in watchlist:
        ind = get_indicators(sid)  # 自動快取優先
        if not ind:
            continue

        sigs = detect_signals(ind)

        if scan_type != "all":
            cfg = SCAN_TYPES.get(scan_type)
            if not cfg or not cfg["filter"](sigs):
                continue

        score = score_signal(ind)
        results.append({
            "stock_id": sid,
            "name": name,
            "close": ind.get("close"),
            "date": ind.get("date"),
            "signals": sigs,
            "score": score,
            "direction": "LONG",
            "indicators": ind,
            "market": market,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def write_signals(results: list):
    """將掃描結果寫入 trade_signals"""
    written = 0
    for r in results:
        for sig_type in r["signals"].keys():
            save_signal(
                r["stock_id"], sig_type,
                r["direction"],
                r["close"],
                r["indicators"],
                r.get("market", "TW"),
            )
            written += 1
    return written


# ── 報告產出 ────────────────────────────────────────────

def print_report(results: list, scan_type: str):
    print(f"\n{'='*55}")
    print(f"🔍 Stephanie 掃描報告 — {scan_type}")
    print(f"{'='*55}")
    if not results:
        print("  （無符合條件的標的）")
        return
    for i, r in enumerate(results[:10], 1):
        sig_list = list(r["signals"].values())
        name = r.get("name", r["stock_id"])
        print(f"\n  {i}. {r['stock_id']}（{name}）收{r['close']} 評分{r['score']}/10")
        print(f"     訊號：{' / '.join(sig_list)}")
    print(f"\n{'='*55}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="掃描並記錄交易訊號")
    parser.add_argument("--scan-type", type=str,
                        choices=["kd_gold_cross","macd_bull","ma_bull","vol_spike","all"],
                        default="all")
    parser.add_argument("--market", type=str, default="TW")
    parser.add_argument("--dry-run", action="store_true",
                        help="只顯示結果，不寫入資料庫")
    args = parser.parse_args()

    results = run_scan(args.scan_type, market=args.market, dry_run=args.dry_run)
    print_report(results, args.scan_type)

    if not args.dry_run and results:
        written = write_signals(results)
        print(f"\n✅ 已將 {written} 筆訊號寫入 trade_signals 資料表")
