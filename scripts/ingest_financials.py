#!/usr/bin/env python3
"""
 資料攝取模組 ④：季財報資料（FinMind API）
 用法：python3 ingest_financials.py --stock 4967 --start 2023-01-01
"""

import os
import sys
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
LOG_FILE = Path(__file__).parent.parent / "logs" / "data_ingest.log"
FINMIND_API = "https://api.finmindtrade.com/api/v4"


def get_token() -> str:
    token = os.environ.get("FINMIND_TOKEN", "")
    if token:
        return token
    tf = Path.home() / ".trade_core.env"
    if tf.exists():
        for line in tf.read_text().splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def fetch_financials(stock_id: str, start_date: str, end_date: str, token: str) -> list:
    """從 FinMind 抓季財報"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 抓取 {stock_id} 季財報：{start_date} ~ {end_date}")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data.get('message')}")
    return data.get("data", [])


def save_financials(records: list, stock_id: str):
    """
    寫入 financials 資料表

    FinMind 季財報格式（攤平）：
      date, stock_id, type, origin_name, value

    需要按 date 分組，取出各 type 的 value，再組成一個季度一筆。
    """
    if not records:
        print("⚠️  無財報資料可寫入")
        return 0

    # 按 date 分組
    by_date = defaultdict(dict)
    for r in records:
        date = r.get("date", "")  # e.g. "2025-03-31"
        ftype = r.get("type", "")
        value = r.get("value", 0) or 0
        by_date[date][ftype] = value

    # 轉成季度 record
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0

    for date, fields in sorted(by_date.items()):
        # date 格式 "2025-03-31" → 季度 "2025Q1"
        try:
            year = int(date[:4])
            month = int(date[5:7])
            quarter = f"{year}Q{(month - 1) // 3 + 1}"
        except ValueError:
            continue

        eps = fields.get("EPS")
        revenue = fields.get("Revenue")
        gross_profit = fields.get("GrossProfit")
        gross_margin = (gross_profit / revenue * 100) if (gross_profit and revenue) else None
        operating_income = fields.get("OperatingIncome")
        operating_margin = (operating_income / revenue * 100) if (operating_income and revenue) else None
        net_income = fields.get("IncomeAfterTaxes") or fields.get("TotalConsolidatedProfitForThePeriod")
        net_margin = (net_income / revenue * 100) if (net_income and revenue) else None
        pre_tax = fields.get("PreTaxIncome")

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO financials
                (stock_id, quarter, eps, revenue, gross_profit, gross_margin,
                 operating_income, operating_margin, net_income, net_margin,
                 roe, roa, debt_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stock_id, quarter,
                eps, revenue, gross_profit, gross_margin,
                operating_income, operating_margin, net_income, net_margin,
                None,  # roe（需另外計算）
                None,  # roa（需另外計算）
                None,  # debt_ratio（需另外計算）
            ))
            inserted += 1
        except Exception as e:
            pass

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 financials（{stock_id}）")
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
    parser.add_argument("--start", type=str, default="2023-01-01")
    parser.add_argument("--end", type=str, default="2026-04-20")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token，請設定 ~/.trade_core.env")
        sys.exit(1)

    try:
        records = fetch_financials(args.stock, args.start, args.end, token)
        save_financials(records, args.stock)
        log(f"financials 完成：{args.stock}，共 {len(records)} 筆原始資料")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
