#!/usr/bin/env python3
"""
 資料攝取模組 ②：三大法人買賣（FinMind API）
 用法：python3 ingest_institutional.py --stock 4967 --start 2025-01-01 --end 2026-04-20
"""

import sys
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
FINMIND_API = "https://api.finmindtrade.com/api/v4"
LOG_FILE = Path(__file__).parent.parent / "logs" / "data_ingest.log"


def fetch_institutional(stock_id: str, start_date: str, end_date: str) -> list:
    """從 FinMind 抓三大法人買賣資料"""
    payload = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data": {
            "stock_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
        },
        "token": "",
    }

    print(f"📡 抓取 {stock_id} 法人資料：{start_date} ~ {end_date}")
    resp = requests.post(FINMIND_API, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data}")

    return data.get("data", [])


def save_institutional(records: list):
    """寫入 institutional 資料表"""
    if not records:
        print("⚠️  無法人資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # FinMind 法人資料格式：stock_id, date, buy, sell, name (外圍/投信/自營商)
    # 需要依 name 欄位分組
    formatted = {}
    for r in records:
        key = (r["stock_id"], r["date"])
        if key not in formatted:
            formatted[key] = {
                "stock_id": r["stock_id"],
                "date": r["date"],
                "foreign_buy": 0, "foreign_sell": 0,
                "prop_buy": 0, "prop_sell": 0,
                "dealer_buy": 0, "dealer_sell": 0,
            }

        name = r.get("name", "")
        buy = int(r.get("buy", 0) or 0)
        sell = int(r.get("sell", 0) or 0)

        if "外圍" in name or "Foreign" in name:
            formatted[key]["foreign_buy"] += buy
            formatted[key]["foreign_sell"] += sell
        elif "投信" in name or "Prop" in name:
            formatted[key]["prop_buy"] += buy
            formatted[key]["prop_sell"] += sell
        elif "自營" in name or "Dealer" in name:
            formatted[key]["dealer_buy"] += buy
            formatted[key]["dealer_sell"] += sell

    inserted = 0
    for r in formatted.values():
        r["net_buy"] = (
            (r["foreign_buy"] - r["foreign_sell"])
            + (r["prop_buy"] - r["prop_sell"])
            + (r["dealer_buy"] - r["dealer_sell"])
        )
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO institutional
                (stock_id, date, foreign_buy, foreign_sell, prop_buy, prop_sell,
                 dealer_buy, dealer_sell, net_buy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"], r["date"],
                r["foreign_buy"], r["foreign_sell"],
                r["prop_buy"], r["prop_sell"],
                r["dealer_buy"], r["dealer_sell"],
                r["net_buy"],
            ))
            inserted += 1
        except Exception as e:
            print(f"⚠️ 寫入錯誤：{e}")

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 institutional")
    return inserted


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="三大法人資料攝取")
    parser.add_argument("--stock", type=str, default="4967")
    parser.add_argument("--start", type=str, default="2025-01-01")
    parser.add_argument("--end", type=str, default="2026-04-20")
    args = parser.parse_args()

    try:
        records = fetch_institutional(args.stock, args.start, args.end)
        save_institutional(records)
        log(f"institutional 完成：{args.stock}，共 {len(records)} 筆")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
