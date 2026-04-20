#!/usr/bin/env python3
"""
 Stephanie 量化系統
 股票掃描器（Scanner）
 用途：根據技術指標條件，自動篩選候選股票
"""

import sqlite3
import json
from pathlib import Path
from technical_indicators import generate_signals, get_price_data

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


def scan_kd_gold_cross(min_k=20, max_k=60) -> list:
    """
    篩選 KD 黃金交叉且 K值在合理區間的股票
    （避免已經飆過70以上的黃金交叉）
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    candidates = []
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            continue
        ind = r["indicators"]
        k = ind.get("K")
        d = ind.get("D")
        if k and d and k > d and k < max_k and k > min_k:
            candidates.append({
                "stock_id": sid,
                "close": r["close"],
                "K": k,
                "D": d,
                "score": r["score"],
                "label": r["score_label"],
                "date": r["analyzed_date"],
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def scan_macd_bull() -> list:
    """篩選 MACD 多頭（DIF>DEA 且 MACD_Bar 轉正）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    candidates = []
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            continue
        ind = r["indicators"]
        dif = ind.get("DIF")
        dea = ind.get("DEA")
        macd_bar = ind.get("MACD_Bar")
        if dif and dea and dif > dea and macd_bar and macd_bar > 0:
            candidates.append({
                "stock_id": sid,
                "close": r["close"],
                "DIF": dif,
                "DEA": dea,
                "MACD_Bar": macd_bar,
                "score": r["score"],
                "label": r["score_label"],
                "date": r["analyzed_date"],
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def scan_volume_surge(threshold: float = 1.8) -> list:
    """篩選量能暴增股票（今日成交量 > 20日均量 * 倍數）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    candidates = []
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            continue
        ind = r["indicators"]
        vol = r["volume"]
        vol5_ma = ind.get("Vol_5MA")
        vol20_ma = ind.get("Vol_20MA")

        if vol5_ma and vol20_ma and vol > vol5_ma * threshold:
            ratio = vol / vol5_ma
            candidates.append({
                "stock_id": sid,
                "close": r["close"],
                "volume": vol,
                "vol_5ma": vol5_ma,
                "vol_ratio": round(ratio, 2),
                "score": r["score"],
                "label": r["score_label"],
                "date": r["analyzed_date"],
            })

    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return candidates


def scan_ma_bull排列() -> list:
    """篩選均線多頭排列（MA5 > MA20 > MA60）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    candidates = []
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            continue
        ind = r["indicators"]
        ma5 = ind.get("MA5")
        ma20 = ind.get("MA20")
        ma60 = ind.get("MA60")
        if all(x is not None for x in [ma5, ma20, ma60]):
            if ma5 > ma20 > ma60:
                candidates.append({
                    "stock_id": sid,
                    "close": r["close"],
                    "MA5": ma5,
                    "MA20": ma20,
                    "MA60": ma60,
                    "score": r["score"],
                    "label": r["score_label"],
                    "date": r["analyzed_date"],
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def run_all_scans() -> dict:
    """一口氣跑所有掃描，回傳結果"""
    print("🔍 Stephanie 股票掃描器")
    print("=" * 50)

    results = {}

    print("\n📌 掃描 1：KD 黃金交叉（低檔）")
    print("-" * 40)
    kd = scan_kd_gold_cross()
    results["kd_gold_cross"] = kd[:10]
    for i, c in enumerate(kd[:10], 1):
        print(f"  {i}. {c['stock_id']} 收{c['close']} | K={c['K']} D={c['D']} | 評分{c['score']}/10 {c['label']}")

    print("\n📌 掃描 2：MACD 多頭")
    print("-" * 40)
    macd = scan_macd_bull()
    results["macd_bull"] = macd[:10]
    for i, c in enumerate(macd[:10], 1):
        print(f"  {i}. {c['stock_id']} 收{c['close']} | DIF={c['DIF']} DEA={c['DEA']} | 評分{c['score']}/10")

    print("\n📌 掃描 3：量能暴增（>1.8倍）")
    print("-" * 40)
    vol = scan_volume_surge(1.8)
    results["volume_surge"] = vol[:10]
    for i, c in enumerate(vol[:10], 1):
        print(f"  {i}. {c['stock_id']} 收{c['close']} | 量比{c['vol_ratio']}x | 評分{c['score']}/10")

    print("\n📌 掃描 4：均線多頭排列")
    print("-" * 40)
    ma = scan_ma_bull排列()
    results["ma_bull"] = ma[:10]
    for i, c in enumerate(ma[:10], 1):
        print(f"  {i}. {c['stock_id']} 收{c['close']} | MA5={c['MA5']} MA20={c['MA20']} MA60={c['MA60']} | 評分{c['score']}/10")

    print(f"\n{'='*50}")
    print("✅ 掃描完成")
    return results


if __name__ == "__main__":
    run_all_scans()
