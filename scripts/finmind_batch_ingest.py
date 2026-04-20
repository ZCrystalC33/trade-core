#!/usr/bin/env python3
"""
FinMind SDK 批次增量攝取腳本（同步版）

測試驗證的正確用法：
  - DataLoader().taiwan_stock_daily() → 直接返回 DataFrame（SDK 內部併發）
  - tqdm 會自動顯示進度條
  - DataFrame.to_dict(orient='records') 才能寫入 SQLite

用法：
  python3 finmind_batch_ingest.py                                    # 全量日K+法人，limit=50
  python3 finmind_batch_ingest.py --dataset daily_price              # 只跑日K
  python3 finmind_batch_ingest.py --dataset institutional            # 只跑法人
  python3 finmind_batch_ingest.py --stocks-limit 10 --since 2025-01-01
"""

import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

from tqdm import tqdm

from FinMind.data import DataLoader

dl = DataLoader()

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
LOG_PATH = Path(__file__).parent.parent / "logs" / "finmind_ingest.log"
BATCH_SIZE = 50
BATCH_DELAY = 1.0   # seconds between batches to avoid rate limiting
SINCE_DEFAULT = "2010-01-01"

# ── Token ────────────────────────────────────────────────────────────────────

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


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db_max_date(conn: sqlite3.Connection, table: str, date_col: str = "date",
                    where: str = "") -> str | None:
    sql = f"SELECT MAX({date_col}) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def get_stock_ids_from_db(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id"
    ).fetchall()
    return [r[0] for r in rows]


def list_to_df(token: str, stock_ids: list[str]) -> list[dict]:
    """
    Call FinMind API with a list of up to BATCH_SIZE stock_ids.
    Uses use_async internally → tqdm progress bar appears automatically.
    Returns list of dict records.
    """
    return dl.taiwan_stock_info(
        token=token,
    ).to_dict(orient="records")


def fetch_stock_list(token: str) -> list[str]:
    """取得全市場股票代號列表（從 FinMind）"""
    records = list_to_df(token, [])
    return sorted(set(r["stock_id"] for r in records if r.get("stock_id")))


# ── Write helpers ────────────────────────────────────────────────────────────

def write_daily_price(conn: sqlite3.Connection, records: list[dict]) -> int:
    """寫入 daily_price：欄位 stock_id, date, open, high, low, close, volume"""
    n = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO daily_price
                    (stock_id, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"],
                r["date"],
                r["open"],
                r["max"],       # FinMind uses 'max' for high
                r["min"],       # FinMind uses 'min' for low
                r["close"],
                r.get("Trading_Volume", 0),
            ))
            n += 1
        except Exception:
            pass
    return n


def write_institutional(conn: sqlite3.Connection, records: list[dict]) -> int:
    """
    寫入 institutional 表。
    同一 stock_id+date 的多筆法人（Foreign/Prop/Dealer）合併成一列。

    欄位：stock_id, date, foreign_buy, foreign_sell,
          prop_buy, prop_sell, dealer_buy, dealer_sell, net_buy
    """
    # group by (stock_id, date)
    grouped: dict[tuple, dict] = defaultdict(lambda: dict(
        foreign_buy=0, foreign_sell=0,
        prop_buy=0,    prop_sell=0,
        dealer_buy=0, dealer_sell=0,
    ))
    for r in records:
        key = (r.get("stock_id", ""), r.get("date", ""))
        name = r.get("name", "")
        buy  = int(r.get("buy",  0) or 0)
        sell = int(r.get("sell", 0) or 0)
        g = grouped[key]
        if "Foreign" in name or "外語" in name:
            g["foreign_buy"]  += buy
            g["foreign_sell"] += sell
        elif "Prop" in name or "投信" in name:
            g["prop_buy"]  += buy
            g["prop_sell"] += sell
        elif "Dealer" in name or "自營" in name:
            g["dealer_buy"]  += buy
            g["dealer_sell"] += sell

    n = 0
    for (stock_id, d), g in grouped.items():
        net = (g["foreign_buy"]  - g["foreign_sell"]
             + g["prop_buy"]     - g["prop_sell"]
             + g["dealer_buy"]   - g["dealer_sell"])
        try:
            conn.execute("""
                INSERT OR REPLACE INTO institutional
                    (stock_id, date,
                     foreign_buy, foreign_sell,
                     prop_buy, prop_sell,
                     dealer_buy, dealer_sell,
                     net_buy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stock_id, d,
                g["foreign_buy"],  g["foreign_sell"],
                g["prop_buy"],     g["prop_sell"],
                g["dealer_buy"],   g["dealer_sell"],
                net,
            ))
            n += 1
        except Exception:
            pass
    return n


# ── Core fetchers (synchronous) ───────────────────────────────────────────────

def fetch_daily_price_batch(token: str, stock_ids: list[str],
                            start: str, end: str) -> list[tuple[str, list[dict]]]:
    """
    Fetch daily price for a list of stock_ids in ONE SDK call.
    SDK internal async + tqdm → progress bar shown automatically.
    Returns [(stock_id, records), ...]  (stock_id repeated per record)
    """
    df = dl.taiwan_stock_daily(
        token=token,
        stock_id=stock_ids,        # SDK accepts list
        start_date=start,
        end_date=end,
    )
    records = df.to_dict(orient="records")
    # tag each record with its stock_id (already in record from FinMind)
    return [(r["stock_id"], records)] if records else []


def fetch_institutional_batch(token: str, stock_ids: list[str],
                               start: str, end: str) -> list[dict]:
    """Fetch institutional data for a list of stock_ids."""
    df = dl.taiwan_stock_institutional(
        token=token,
        stock_id=stock_ids,
        start_date=start,
        end_date=end,
    )
    return df.to_dict(orient="records")


# ── Ingestion pipelines ───────────────────────────────────────────────────────

def ingest_daily_price(stock_ids: list[str], since: str | None,
                       token: str, batch_size: int = BATCH_SIZE,
                       delay: float = BATCH_DELAY) -> tuple[int, list[str]]:
    """
    日K增量攝取：每批次 stock_ids → SDK 一次抓取 → DataFrame.to_dict → DB
    增量：取 DB max(date) 之後的資料；無則用 since 或 2010-01-01
    """
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors: list[str] = []

    end = date.today().isoformat()

    # build start date: max date already in DB, else since
    db_max = get_db_max_date(conn, "daily_price")
    start = db_max if db_max else (since or SINCE_DEFAULT)
    print(f"[daily_price] start={start}  end={end}  stocks={len(stock_ids)}")

    n = len(stock_ids)
    for i in tqdm(range(0, n, batch_size), desc="[daily_price]", unit="batch"):
        batch = stock_ids[i:i + batch_size]

        try:
            df = dl.taiwan_stock_daily(
                token=token,
                stock_id=batch,
                start_date=start,
                end_date=end,
            )
            records = df.to_dict(orient="records")
            if records:
                n_written = write_daily_price(conn, records)
                total_wrote += n_written
        except Exception as e:
            errors.append(f"batch[{i}]: {e}")

        conn.commit()

        if i + batch_size < n:
            time.sleep(delay)

    conn.close()
    return total_wrote, errors


def ingest_institutional_data(stock_ids: list[str], since: str | None,
                               token: str, batch_size: int = BATCH_SIZE,
                               delay: float = BATCH_DELAY) -> tuple[int, list[str]]:
    """
    法人輪動資料增量攝取。
    欄位：stock_id, date, foreign_buy/sell, prop_buy/sell, dealer_buy/sell, net_buy
    """
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors: list[str] = []

    end = date.today().isoformat()

    # incremental: find latest date per stock in DB
    db_max = get_db_max_date(conn, "institutional")
    start = db_max if db_max else (since or SINCE_DEFAULT)
    print(f"[institutional] start={start}  end={end}  stocks={len(stock_ids)}")

    n = len(stock_ids)
    for i in tqdm(range(0, n, batch_size), desc="[institutional]", unit="batch"):
        batch = stock_ids[i:i + batch_size]

        try:
            df = dl.taiwan_stock_institutional(
                token=token,
                stock_id=batch,
                start_date=start,
                end_date=end,
            )
            records = df.to_dict(orient="records")
            if records:
                n_written = write_institutional(conn, records)
                total_wrote += n_written
        except Exception as e:
            errors.append(f"batch[{i}]: {e}")

        conn.commit()

        if i + batch_size < n:
            time.sleep(delay)

    conn.close()
    return total_wrote, errors


# ── Stock list resolution ────────────────────────────────────────────────────

def resolve_stock_ids(limit: int | None, token: str) -> list[str]:
    """
    回傳要攝取的股票代號列表。
    優先從 DB 的 daily_price 拿；DB 空的話從 FinMind 抓全市場列表再 limit。
    """
    conn = sqlite3.connect(DB_PATH)
    db_ids = get_stock_ids_from_db(conn)
    conn.close()

    if db_ids:
        print(f"Using {len(db_ids)} stock IDs from DB (all in daily_price)")
        return db_ids[:limit] if limit else db_ids

    # DB empty → fetch from FinMind
    print("DB empty, fetching stock list from FinMind …")
    all_ids = fetch_stock_list(token)
    chosen = all_ids[:limit] if limit else all_ids
    print(f"Fetched {len(chosen)} stock IDs from FinMind")
    return chosen


# ── CLI ──────────────────────────────────────────────────────────────────────

DATASETS = {
    "daily_price":    ingest_daily_price,
    "institutional":  ingest_institutional_data,
}


def main():
    parser = argparse.ArgumentParser(description="FinMind 批次增量攝取（同步版）")
    parser.add_argument(
        "--dataset",
        choices=list(DATASETS.keys()),
        default="daily_price",
        help="要攝取的資料集（default: daily_price）",
    )
    parser.add_argument(
        "--stocks-limit",
        type=int,
        default=50,
        dest="stocks_limit",
        help="最多處理幾檔股票（default: 50）",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="全量起始日期（YYYY-MM-DD），適用於 DB 無資料時的起始點",
    )
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("ERROR: FINMIND_TOKEN not set. Set FINMIND_TOKEN env var or write to ~/.trade_core.env",
              file=sys.stderr)
        sys.exit(1)

    stock_ids = resolve_stock_ids(args.stocks_limit, token)

    if not stock_ids:
        print("No stock IDs to process. Exiting.")
        sys.exit(0)

    # ── Logging ──
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    started_at = str(date.today())

    ingest_fn = DATASETS[args.dataset]
    wrote, errors = ingest_fn(stock_ids, args.since, token)

    # ── Log result ──
    with open(LOG_PATH, "a") as f:
        f.write(f"[{started_at}] dataset={args.dataset}  wrote={wrote}  errors={len(errors)}\n")
        for e in errors:
            f.write(f"  ERROR: {e}\n")

    if errors:
        print(f"\n⚠  {len(errors)} batch errors — see {LOG_PATH}")
        for e in errors[:5]:
            print(f"  {e}")

    print(f"\n✅ Done — wrote {wrote} rows  dataset={args.dataset}  since={args.since or 'auto'}")


if __name__ == "__main__":
    main()
