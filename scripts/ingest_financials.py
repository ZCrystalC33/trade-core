#!/usr/bin/env python3
"""
 資料攝取模組 ④：季財報資料（FinMind API）
 用法：python3 ingest_financials.py --stock 4967 --start 2024Q1 --end 2025Q4
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


def fetch_quarterly_financials(stock_id: str) -> list:
    """從 FinMind 抓季財報（損益表）"""
    payload = {
        "dataset": "TaiwanStockFinancialStatements",
        "data": {"stock_id": stock_id},
        "token": "",
    }

    print(f"📡 抓取 {stock_id} 季財報")
    resp = requests.post(FINMIND_API, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data}")

    return data.get("data", [])


def save_financials(records: list):
    """寫入 financials 資料表"""
    if not records:
        print("⚠️  無財報資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    inserted = 0
    for r in records:
        try:
            quarter = r.get("quarter", "")
            # 格式：2025Q1
            cursor.execute("""
                INSERT OR REPLACE INTO financials
                (stock_id, quarter, eps, revenue, gross_profit, gross_margin,
                 operating_income, operating_margin, net_income, net_margin, roe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"],
                quarter,
                r.get("eps"),
                r.get("revenue"),
                r.get("gross_profit"),
                r.get("gross_profit_margin"),
                r.get("operating_income"),
                r.get("operating_income_margin"),
                r.get("net_income"),
                r.get("net_income_margin"),
                r.get("roe"),
            ))
            inserted += 1
        except Exception as e:
            print(f"⚠️ 寫入錯誤（{quarter}）：{e}")

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 financials")
    return inserted


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="季財報資料攝取")
    parser.add_argument("--stock", type=str, default="4967")
    args = parser.parse_args()

    try:
        records = fetch_quarterly_financials(args.stock)
        save_financials(records)
        log(f"financials 完成：{args.stock}，共 {len(records)} 筆")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
