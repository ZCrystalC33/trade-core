#!/usr/bin/env python3
"""
 Stephanie 量化系統
 股票掃描器（Scanner）
 用途：根據技術指標條件，自動篩選候選股票
"""

import sqlite3
import json
from pathlib import Path
from technical_indicators import generate_signals, get_price_data, get_price_data_batch, calc_kd, calc_macd, calc_ma
import logging

try:
    import jin10_client as jc
    JIN10_AVAILABLE = True
except ImportError:
    JIN10_AVAILABLE = False
    jc = None

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
    import logging
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            logging.debug(f"Skipping {sid}: {r['error']}")
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
    import logging
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            logging.debug(f"Skipping {sid}: {r['error']}")
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
    import logging
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            logging.debug(f"Skipping {sid}: {r['error']}")
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
    import logging
    for sid in stocks:
        r = generate_signals(sid)
        if "error" in r:
            logging.debug(f"Skipping {sid}: {r['error']}")
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
    """一口氣跑所有掃描，回傳結果（含 Jin10 宏觀警訊）"""
    print("🔍 Stephanie 股票掃描器")
    print("=" * 50)

    results = {}

    # ── 宏觀前置檢查 ────────────────────────────────────────
    if JIN10_AVAILABLE:
        try:
            macro_score = jc.get_macro_sentiment()
            macro_flag = jc.check_macro_threshold(macro_score)
            print(f"\n🌐 宏觀情緒：{macro_score:.1f}/100  [{macro_flag}]")

            alert = jc.check_macro_alerts()
            if alert:
                print(f"  {alert}")
        except Exception as e:
            macro_score = None
            macro_flag = "N/A"
            print(f"\n⚠️  宏觀數據取得失敗：{e}")
    else:
        macro_score = None
        macro_flag = "N/A"
        print("\n⚠️  Jin10 未啟用（未安裝或無法載入）")

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

    # ── 宏觀結論 ───────────────────────────────────────────
    if macro_flag != "N/A":
        print(f"\n{'='*50}")
        if macro_flag == "BULL":
            print("✅ 宏觀偏多，策略積極（可參考推薦股票）")
        elif macro_flag == "BEAR":
            print("⚠️  宏觀偏空，策略謹慎（注意倉位控制）")
        else:
            print("➡️  宏觀中性，觀望為主")
        print("✅ 掃描完成")
    else:
        print(f"\n{'='*50}")
        print("✅ 掃描完成")
    return results




# ── Batch Scan Functions (N+1 Query Fix) ─────────────────────────────────

def scan_kd_batch(stock_ids: list, min_k: float = 20, max_k: float = 80) -> list:
    """批量 KD 黃金交叉掃描（單一 DB 查詢）"""
    if not stock_ids:
        return []
    
    all_data = get_price_data_batch(stock_ids, days=120)
    
    candidates = []
    for sid, data in all_data.items():
        if len(data) < 60:
            logging.debug(f"Skipping {sid}: insufficient data")
            continue
        
        try:
            closes = [d["close"] for d in data]
            highs = [d["high"] for d in data]
            lows = [d["low"] for d in data]
            
            k, d = calc_kd(highs, lows, closes)
            if k and d and k[-1] > d[-1] and max_k > k[-1] > min_k:
                candidates.append({
                    "stock_id": sid,
                    "close": closes[-1],
                    "K": k[-1],
                    "D": d[-1],
                })
        except Exception as e:
            logging.debug(f"Error processing {sid}: {e}")
    
    candidates.sort(key=lambda x: x["K"], reverse=True)
    return candidates


def scan_macd_batch(stock_ids: list) -> list:
    """批量 MACD 多頭掃描（單一 DB 查詢）"""
    if not stock_ids:
        return []
    
    all_data = get_price_data_batch(stock_ids, days=120)
    
    candidates = []
    for sid, data in all_data.items():
        if len(data) < 60:
            continue
        
        try:
            closes = [d["close"] for d in data]
            dif, dea, macd_bar = calc_macd(closes)
            
            if dif and dea and dif[-1] > dea[-1] and macd_bar[-1] > 0:
                candidates.append({
                    "stock_id": sid,
                    "close": closes[-1],
                    "DIF": dif[-1],
                    "DEA": dea[-1],
                    "MACD_Bar": macd_bar[-1],
                })
        except Exception as e:
            logging.debug(f"Error processing {sid}: {e}")
    
    candidates.sort(key=lambda x: x["DIF"], reverse=True)
    return candidates


def scan_volume_surge_batch(stock_ids: list, threshold: float = 1.8) -> list:
    """批量量能暴增掃描（單一 DB 查詢）"""
    if not stock_ids:
        return []
    
    all_data = get_price_data_batch(stock_ids, days=120)
    
    candidates = []
    for sid, data in all_data.items():
        if len(data) < 25:
            continue
        
        try:
            closes = [d["close"] for d in data]
            volumes = [d["volume"] for d in data]
            
            vol5_ma = calc_ma(volumes, 5)
            vol20_ma = calc_ma(volumes, 20)
            
            vol5 = vol5_ma[-1] if vol5_ma else None
            vol20 = vol20_ma[-1] if vol20_ma else None
            vol = volumes[-1]
            
            if vol5 and vol20 and vol > vol5 * threshold:
                candidates.append({
                    "stock_id": sid,
                    "close": closes[-1],
                    "vol_ratio": vol / vol5,
                })
        except Exception as e:
            logging.debug(f"Error processing {sid}: {e}")
    
    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return candidates


def scan_ma_bull_batch(stock_ids: list) -> list:
    """批量均線多頭排列掃描（單一 DB 查詢）"""
    if not stock_ids:
        return []
    
    all_data = get_price_data_batch(stock_ids, days=120)
    
    candidates = []
    for sid, data in all_data.items():
        if len(data) < 65:
            continue
        
        try:
            closes = [d["close"] for d in data]
            
            ma5 = calc_ma(closes, 5)
            ma20 = calc_ma(closes, 20)
            ma60 = calc_ma(closes, 60)
            
            ma5_v = ma5[-1] if ma5 else None
            ma20_v = ma20[-1] if ma20 else None
            ma60_v = ma60[-1] if ma60 else None
            
            if all(x is not None for x in [ma5_v, ma20_v, ma60_v]):
                if ma5_v > ma20_v > ma60_v:
                    candidates.append({
                        "stock_id": sid,
                        "close": closes[-1],
                        "MA5": ma5_v,
                        "MA20": ma20_v,
                        "MA60": ma60_v,
                    })
        except Exception as e:
            logging.debug(f"Error processing {sid}: {e}")
    
    candidates.sort(key=lambda x: x["close"], reverse=True)
    return candidates


def run_all_scans_batch() -> dict:
    """一口氣跑所有批量掃描（優化版）"""
    print("🔍 Stephanie 股票掃描器 (Batch Mode)")
    print("=" * 50)
    
    # Fetch all stocks once
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stock_ids = [r[0] for r in cursor.fetchall()]
    conn.close()
    
    print(f"📊 共 {len(stock_ids)} 檔股票")
    
    results = {}
    
    print("\n📌 掃描 1：KD 黃金交叉")
    print("-" * 40)
    kd = scan_kd_batch(stock_ids, min_k=20, max_k=80)
    results["kd_cross"] = kd[:10]
    for i, c in enumerate(kd[:10], 1):
        print(f"  {i}. {c['stock_id']} K={c['K']:.1f} D={c['D']:.1f}")
    
    print("\n📌 掃描 2：MACD 多頭")
    print("-" * 40)
    macd = scan_macd_batch(stock_ids)
    results["macd_bull"] = macd[:10]
    for i, c in enumerate(macd[:10], 1):
        print(f"  {i}. {c['stock_id']} DIF={c['DIF']:.2f} DEA={c['DEA']:.2f}")
    
    print("\n📌 掃描 3：量能暴增")
    print("-" * 40)
    vol = scan_volume_surge_batch(stock_ids, 1.8)
    results["volume_surge"] = vol[:10]
    for i, c in enumerate(vol[:10], 1):
        print(f"  {i}. {c['stock_id']} 量比={c['vol_ratio']:.1f}x")
    
    print("\n📌 掃描 4：均線多頭排列")
    print("-" * 40)
    ma = scan_ma_bull_batch(stock_ids)
    results["ma_bull"] = ma[:10]
    for i, c in enumerate(ma[:10], 1):
        print(f"  {i}. {c['stock_id']} MA5={c['MA5']:.1f} MA20={c['MA20']:.1f} MA60={c['MA60']:.1f}")
    
    print(f"\n{'='*50}")
    print("✅ 掃描完成")
    return results


if __name__ == "__main__":
    run_all_scans_batch()


if __name__ == "__main__":
    run_all_scans()
