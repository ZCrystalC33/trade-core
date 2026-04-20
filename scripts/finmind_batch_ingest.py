#!/usr/bin/env python3
"""
FinMind SDK 批次增量攝取腳本
使用 FinMind Python SDK login_by_token + taiwan_stock_* (use_async=True)

用法：
  python3 finmind_batch_ingest.py                           # 全部 dataset，預設全量
  python3 finmind_batch_ingest.py --dataset daily_price    # 只跑日K
  python3 finmind_batch_ingest.py --stocks-limit 10        # 只測試 10 檔
  python3 finmind_batch_ingest.py --since 2025-01-01        # 從指定日期增量
"""

import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

import asyncio
from tqdm import tqdm

# FinMind SDK
from FinMind.Report import Login
import FinMind.DataServer as dl

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
LOG_FILE = Path(__file__).parent.parent / "logs" / "finmind_ingest.log"

# ── Token 讀取 ──────────────────────────────────────────────
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


# ── 資料庫 helpers ──────────────────────────────────────────
def get_last_date(conn: sqlite3.Connection, table: str, col: str = "date",
                  where: str = "") -> str | None:
    """回傳資料庫中某表某股票的最後一筆日期，無資料則回傳 None"""
    sql = f"SELECT MAX({col}) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def stock_ids_from_db(conn: sqlite3.Connection) -> list[str]:
    """取得資料庫中已有日K的股票代號（維持與舊版一致）"""
    rows = conn.execute(
        "SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id"
    ).fetchall()
    return [r[0] for r in rows]


def write_daily_price(conn: sqlite3.Connection, records: list[dict]) -> int:
    n = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO daily_price
                (stock_id, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (r["stock_id"], r["date"],
                  r["open"], r["max"], r["min"], r["close"],
                  r.get("Trading_Volume", 0)))
            n += 1
        except Exception:
            pass
    return n


def write_institutional(conn: sqlite3.Connection, records: list[dict]) -> int:
    """寫入 institutional 表（同一日期多個法人要合併）"""
    grouped = defaultdict(lambda: dict(
        foreign_buy=0, foreign_sell=0,
        prop_buy=0, prop_sell=0,
        dealer_buy=0, dealer_sell=0,
    ))
    for r in records:
        d = r.get("date", "")
        name = r.get("name", "")
        buy = int(r.get("buy") or 0)
        sell = int(r.get("sell") or 0)
        g = grouped[d]
        if "Foreign" in name:
            g["foreign_buy"] += buy
            g["foreign_sell"] += sell
        elif "Prop" in name or "投信" in name:
            g["prop_buy"] += buy
            g["prop_sell"] += sell
        elif "Dealer" in name or "自營" in name:
            g["dealer_buy"] += buy
            g["dealer_sell"] += sell

    n = 0
    for d, g in grouped.items():
        net = (g["foreign_buy"] - g["foreign_sell"]
               + g["prop_buy"] - g["prop_sell"]
               + g["dealer_buy"] - g["dealer_sell"])
        try:
            conn.execute("""
                INSERT OR REPLACE INTO institutional
                (stock_id, date, foreign_buy, foreign_sell,
                 prop_buy, prop_sell, dealer_buy, dealer_sell, net_buy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (records[0]["stock_id"], d,
                  g["foreign_buy"], g["foreign_sell"],
                  g["prop_buy"], g["prop_sell"],
                  g["dealer_buy"], g["dealer_sell"], net))
            n += 1
        except Exception:
            pass
    return n


def write_margin_short(conn: sqlite3.Connection, records: list[dict]) -> int:
    n = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO margin_short
                (stock_id, date, margin_buy, margin_buy_amount, margin_sell,
                 margin_balance, short_sell, short_cover, short_balance,
                 margin_call, short_call, lend_balance, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"], r["date"],
                int(r.get("MarginBuy", 0)), float(r.get("MarginBuyAmount", 0)),
                int(r.get("MarginSell", 0)),
                int(r.get("MarginBalance", 0)),
                int(r.get("ShortSell", 0)),
                int(r.get("ShortCover", 0)),
                int(r.get("ShortBalance", 0)),
                float(r.get("MarginCall", 0)),
                float(r.get("ShortCall", 0)),
                int(r.get("LendBalance", 0)),
                now,
            ))
            n += 1
        except Exception:
            pass
    return n


def write_monthly_revenue(conn: sqlite3.Connection, records: list[dict]) -> int:
    n = 0
    for r in records:
        rm = r.get("date", "")[:7]  # YYYY-MM
        try:
            conn.execute("""
                INSERT OR REPLACE INTO monthly_revenue
                (stock_id, revenue_month, revenue, yoy_change, mom_change)
                VALUES (?, ?, ?, ?, ?)
            """, (
                r["stock_id"], rm,
                float(r.get("revenue", 0) or 0),
                r.get("yoy_ratio"),
                r.get("mom_ratio"),
            ))
            n += 1
        except Exception:
            pass
    return n


def write_stock_info(conn: sqlite3.Connection, records: list[dict]):
    """寫入 stock_info 表（股票基本資料）"""
    if not records:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest = records[-1]
    try:
        conn.execute("""
            INSERT OR REPLACE INTO stock_info
            (stock_id, name, industry, listed_date, capital, shares,
             par_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            latest["stock_id"],
            latest.get("stock_name", latest.get("name", "")),
            latest.get("industry_category", ""),
            latest.get("date", ""),
            None, None, 10.0, now,
        ))
        return 1
    except Exception:
        return 0


# ── 核心非同步批次抓取 ───────────────────────────────────────

async def _fetch_one(dataset: str, stock_id: str,
                     start: str, end: str,
                     token: str) -> tuple[str, list[dict], str]:
    """單一股票非同步抓取，回傳 (stock_id, records, error_msg)"""
    try:
        data = await dl.taiwan_stock_daily(
            token=token,
            stock_id=stock_id,
            start_date=start,
            end_date=end,
            use_async=True,
        )
        return stock_id, data, ""
    except Exception as e:
        return stock_id, [], str(e)


async def batch_fetch(dataset: str,
                      stock_ids: list[str],
                      start: str, end: str,
                      token: str,
                      batch_size: int = 50,
                      delay: float = 0.5) -> list[tuple[str, list[dict], str]]:
    """
    批次非同步抓取。
    每 batch_size 檔為一批，批內並行，批次間延遲 delay 秒。
    回傳 [(stock_id, records, error), ...]
    """
    results = []
    n = len(stock_ids)

    for i in tqdm(range(0, n, batch_size), desc=f"[{dataset}] 批次",
                  unit="batch"):
        batch = stock_ids[i:i + batch_size]

        if dataset == "taiwan_stock_daily":
            tasks = [_fetch_one("taiwan_stock_daily", sid, start, end, token)
                     for sid in batch]
        elif dataset == "taiwan_stock_institutional":
            tasks = [dl.taiwan_stock_institutional(
                        token=token, stock_id=sid,
                        start_date=start, end_date=end, use_async=True)
                     .then(lambda r, s=sid: (s, r, ""))
                     .catch(lambda e, s=sid: (s, [], str(e)))
                     for sid in batch]
        elif dataset == "taiwan_stock_margin":
            tasks = [dl.taiwan_stock_margin(
                        token=token, stock_id=sid,
                        start_date=start, end_date=end, use_async=True)
                     .then(lambda r, s=sid: (s, r, ""))
                     .catch(lambda e, s=sid: (s, [], str(e)))
                     for sid in batch]
        elif dataset == "taiwan_stock_per":
            tasks = [dl.taiwan_stock_per(
                        token=token, stock_id=sid,
                        start_date=start, end_date=end, use_async=True)
                     .then(lambda r, s=sid: (s, r, ""))
                     .catch(lambda e, s=sid: (s, [], str(e)))
                     for sid in batch]
        elif dataset == "taiwan_stock_pbr":
            tasks = [dl.taiwan_stock_pbr(
                        token=token, stock_id=sid,
                        start_date=start, end_date=end, use_async=True)
                     .then(lambda r, s=sid: (s, r, ""))
                     .catch(lambda e, s=sid: (s, [], str(e)))
                     for sid in batch]
        elif dataset == "taiwan_stock_month_revenue":
            tasks = [dl.taiwan_stock_month_revenue(
                        token=token, stock_id=sid,
                        start_date=start, use_async=True)
                     .then(lambda r, s=sid: (s, r, ""))
                     .catch(lambda e, s=sid: (s, [], str(e)))
                     for sid in batch]
        else:
            tasks = []

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for br in batch_results:
            if isinstance(br, Exception):
                results.append(("", [], str(br)))
            else:
                results.append(br)

        # 防止瞬間流量過大（批次間 delay）
        if i + batch_size < n:
            await asyncio.sleep(delay)

    return results


# ── 各資料集攝取流程 ─────────────────────────────────────────

async def ingest_daily_price(stock_ids: list[str], since: str | None,
                             token: str, batch_size: int,
                             delay: float):
    """taiwan_stock_daily → daily_price 表（增量：只取高於 DB 最後日期的資料）"""
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors = []

    # 分批處理，一批內並行
    for i in tqdm(range(0, len(stock_ids), batch_size), desc="[daily_price]"):
        batch = stock_ids[i:i + batch_size]

        # 並行抓取（每支股票的 start_date 各自判斷）
        async def fetch_one(sid: str):
            last = get_last_date(conn, "daily_price", where=f"stock_id='{sid}'")
            start = last if last else since if since else "2010-01-01"
            try:
                data = await dl.taiwan_stock_daily(
                    token=token, stock_id=sid,
                    start_date=start,
                    end_date=date.today().isoformat(),
                    use_async=True,
                )
                return sid, data, ""
            except Exception as e:
                return sid, [], str(e)

        tasks = [fetch_one(s) for s in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        written = 0
        for r in results:
            if isinstance(r, Exception):
                errors.append(f"EXCEPTION: {r}")
                continue
            sid, records, err = r
            if err:
                errors.append(f"{sid}: {err}")
                continue
            if records:
                n = write_daily_price(conn, records)
                written += n

        total_wrote += written
        await asyncio.sleep(delay)

    conn.close()
    return total_wrote, errors


async def ingest_institutional(stock_ids: list[str], since: str | None,
                              token: str, batch_size: int,
                              delay: float):
    """taiwan_stock_institutional → institutional 表"""
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors = []

    end = date.today().isoformat()
    for i in tqdm(range(0, len(stock_ids), batch_size), desc="[institutional]"):
        batch = stock_ids[i:i + batch_size]
        start = since if since else "2010-01-01"

        tasks = [
            dl.taiwan_stock_institutional(
                token=token, stock_id=sid,
                start_date=start, end_date=end, use_async=True)
            .then(lambda r, s=sid: (s, r, ""))
            .catch(lambda e, s=sid: (s, [], str(e)))
            for sid in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                errors.append(f"EXCEPTION: {r}")
                continue
            sid, records, err = r
            if err:
                errors.append(f"{sid}: {err}")
                continue
            if records:
                total_wrote += write_institutional(conn, records)

        await asyncio.sleep(delay)

    conn.close()
    return total_wrote, errors


async def ingest_margin(stock_ids: list[str], since: str | None,
                        token: str, batch_size: int,
                        delay: float):
    """taiwan_stock_margin → margin_short 表"""
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors = []

    end = date.today().isoformat()
    for i in tqdm(range(0, len(stock_ids), batch_size), desc="[margin_short]"):
        batch = stock_ids[i:i + batch_size]
        start = since if since else "2010-01-01"

        tasks = [
            dl.taiwan_stock_margin(
                token=token, stock_id=sid,
                start_date=start, end_date=end, use_async=True)
            .then(lambda r, s=sid: (s, r, ""))
            .catch(lambda e, s=sid: (s, [], str(e)))
            for sid in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                errors.append(f"EXCEPTION: {r}")
                continue
            sid, records, err = r
            if err:
                errors.append(f"{sid}: {err}")
                continue
            if records:
                total_wrote += write_margin_short(conn, records)

        await asyncio.sleep(delay)

    conn.close()
    return total_wrote, errors


async def ingest_per_pbr(stock_ids: list[str], since: str | None,
                          token: str, batch_size: int,
                          delay: float):
    """taiwan_stock_per / taiwan_stock_pbr → stock_info 表（更新 per / pbr 欄位）"""
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors = []

    end = date.today().isoformat()
    for i in tqdm(range(0, len(stock_ids), batch_size), desc="[PER/PBR]"):
        batch = stock_ids[i:i + batch_size]
        start = since if since else "2010-01-01"

        # PER
        per_tasks = [
            dl.taiwan_stock_per(
                token=token, stock_id=sid,
                start_date=start, end_date=end, use_async=True)
            .then(lambda r, s=sid: (s, r, "per"))
            .catch(lambda e, s=sid: (s, [], "per", str(e)))
            for sid in batch
        ]
        # PBR
        pbr_tasks = [
            dl.taiwan_stock_pbr(
                token=token, stock_id=sid,
                start_date=start, end_date=end, use_async=True)
            .then(lambda r, s=sid: (s, r, "pbr"))
            .catch(lambda e, s=sid: (s, [], "pbr", str(e)))
            for sid in batch
        ]

        per_results = await asyncio.gather(*per_tasks, return_exceptions=True)
        pbr_results = await asyncio.gather(*pbr_tasks, return_exceptions=True)

        per_map: dict[str, dict] = {}
        for r in per_results:
            if isinstance(r, Exception):
                continue
            sid, records, kind, *_ = r if len(r) > 2 else (*r, "")
            if records:
                latest = records[-1]
                per_map[sid] = latest

        for r in pbr_results:
            if isinstance(r, Exception):
                continue
            sid, records, kind, *_ = r if len(r) > 2 else (*r, "")
            if sid in per_map and records:
                per_map[sid].update(records[-1])

        for sid, data in per_map.items():
            try:
                conn.execute("""
                    UPDATE stock_info SET
                        updated_at = ?
                    WHERE stock_id = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sid))
                # 寫入 per_pbr 快取（若 stock_info 表有這些欄位）
                conn.execute("""
                    INSERT OR REPLACE INTO stock_info
                    (stock_id, updated_at)
                    VALUES (?, ?)
                    ON CONFLICT(stock_id) DO UPDATE SET updated_at=excluded.updated_at
                """, (sid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                total_wrote += 1
            except Exception:
                pass

        await asyncio.sleep(delay)

    conn.close()
    return total_wrote, errors


async def ingest_monthly_revenue(stock_ids: list[str], since: str | None,
                                  token: str, batch_size: int,
                                  delay: float):
    """taiwan_stock_month_revenue → monthly_revenue 表"""
    conn = sqlite3.connect(DB_PATH)
    total_wrote = 0
    errors = []

    for i in tqdm(range(0, len(stock_ids), batch_size), desc="[monthly_revenue]"):
        batch = stock_ids[i:i + batch_size]
        start = since if since else "2010-01-01"

        tasks = [
            dl.taiwan_stock_month_revenue(
                token=token, stock_id=sid,
                start_date=start, use_async=True)
            .then(lambda r, s=sid: (s, r, ""))
            .catch(lambda e, s=sid: (s, [], str(e)))
            for sid in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                errors.append(f"EXCEPTION: {r}")
                continue
            sid, records, err = r
            if err:
                errors.append(f"{sid}: {err}")
                continue
            if records:
                total_wrote += write_monthly_revenue(conn, records)

        await asyncio.sleep(delay)

    conn.close()
    return total_wrote, errors


# ── 主要流程 ─────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


async def main_async(args):
    token = get_token()
    if not token:
        log("無 FINMIND_TOKEN，請設定 ~/.trade_core.env 或環境變數", "ERROR")
        sys.exit(1)

    log(f"🔐 FinMind token 取得成功，開始登入...")
    try:
        dl.login_by_token(token=token)
    except Exception as e:
        log(f"FinMind login 失敗：{e}", "ERROR")
        sys.exit(1)

    # ── 取得股票清單 ──────────────────────────────────────
    log("📋 抓取 taiwan_stock_info（完整股票清單）...")
    try:
        all_stocks_raw = await dl.taiwan_stock_info(use_async=True)
        # all_stocks_raw 是 list[dict]，每筆有 stock_id / stock_name / industry_category
        # 先簡單取全部 stock_id 清單
        stock_id_map = {}
        for r in all_stocks_raw:
            sid = r.get("stock_id", "")
            if sid:
                stock_id_map[sid] = r
    except Exception as e:
        log(f"抓取 stock_info 失敗，改用 DB 既有股票：{e}", "WARNING")
        conn = sqlite3.connect(DB_PATH)
        db_ids = stock_ids_from_db(conn)
        conn.close()
        stock_id_map = {sid: {"stock_id": sid} for sid in db_ids}

    stock_ids = list(stock_id_map.keys())
    if args.stocks_limit:
        stock_ids = stock_ids[: args.stocks_limit]

    log(f"📦 股票總數：{len(stock_ids)} 檔（limit={args.stocks_limit}）")

    # 寫入 stock_info 基本資料
    if stock_id_map:
        conn = sqlite3.connect(DB_PATH)
        count = sum(write_stock_info(conn, [v]) for v in stock_id_map.values())
        conn.commit()
        conn.close()
        log(f"✅ stock_info 寫入 {count} 筆記錄")

    # ── 跑哪些 dataset ────────────────────────────────────
    all_datasets = [
        ("taiwan_stock_daily",       ingest_daily_price),
        ("taiwan_stock_institutional", ingest_institutional),
        ("taiwan_stock_margin",     ingest_margin),
        ("taiwan_stock_per",        ingest_per_pbr),
        ("taiwan_stock_month_revenue", ingest_monthly_revenue),
    ]

    if args.dataset and args.dataset != "all":
        all_datasets = [(d, f) for d, f in all_datasets if d == args.dataset]
        if not all_datasets:
            log(f"未知 dataset：{args.dataset}", "ERROR")
            sys.exit(1)

    # ── 執行每一個 dataset ─────────────────────────────────
    total_records = 0
    total_errors = 0

    for dataset_name, ingest_fn in all_datasets:
        log(f"\n{'='*60}")
        log(f"🚀 開始攝取 {dataset_name}（since={args.since or 'auto'}）")
        start_time = time.time()

        wrote, errors = await ingest_fn(
            stock_ids=stock_ids,
            since=args.since,
            token=token,
            batch_size=50,
            delay=0.5,
        )

        elapsed = time.time() - start_time
        total_records += wrote
        total_errors += len(errors)
        log(f"✅ {dataset_name} 完成：{wrote} 筆記錄，{len(errors)} 錯誤，耗時 {elapsed:.1f}s")

    # ── 最終報告 ───────────────────────────────────────────
    log(f"""
{'='*60}
📊 攝取報告
  資料集：{args.dataset or '全部'}
  股票數：{len(stock_ids)}
  寫入紀錄：{total_records}
  錯誤筆數：{total_errors}
{'='*60}""")

    return total_errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FinMind SDK 批次增量攝取（async batch）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
可用 --dataset：
  all（預設）, taiwan_stock_daily, taiwan_stock_institutional,
  taiwan_stock_margin, taiwan_stock_per, taiwan_stock_month_revenue
        """,
    )
    parser.add_argument(
        "--dataset", type=str, default="all",
        help="指定資料集（預設全部）",
    )
    parser.add_argument(
        "--stocks-limit", type=int, default=None,
        help="最多攝取幾檔（用於測試，預設全量）",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="從哪天開始增量（YYYY-MM-DD，預設自動判斷 DB 最後日期）",
    )
    args = parser.parse_args()

    errors = asyncio.run(main_async(args))
    sys.exit(0 if errors == 0 else 1)