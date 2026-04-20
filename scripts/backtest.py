#!/usr/bin/env python3
"""
 Stephanie 回測引擎
 用途：對歷史K線資料測試特定策略的勝率與報酬

 支援策略：
  - KD黃金交叉策略
  - MACD多頭策略
  - 均線多頭排列策略
  - 複合策略（同時滿足多個條件）

 使用方式：
   python3 backtest.py --stock 4967 --strategy kd_cross --start 2025-01-01
   python3 backtest.py --stock 2330 --strategy macd_bull --start 2025-01-01
   python3 backtest.py --stock all --strategy all
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 歷史資料讀取 ──────────────────────────────────────────

def get_adjusted_prices(stock_id: str, start_date: str = "2020-01-01") -> list:
    """
    優先讀取還原價格，若無則用原始價格。
    還原價格精確匹配到小數點後兩位，讀取時保留原精度。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 優先讀取還原價格
    cursor.execute("""
        SELECT date, open, high, low, close, adj_close, volume
        FROM adjusted_daily_price
        WHERE stock_id = ? AND date >= ?
        ORDER BY date ASC
    """, (stock_id, start_date))
    rows = cursor.fetchall()

    if rows:
        conn.close()
        return [dict(r) for r in rows]

    # 沒有還原價格，用原始價格
    cursor.execute("""
        SELECT date, open, high, low, close, close as adj_close, volume
        FROM daily_price
        WHERE stock_id = ? AND date >= ?
        ORDER BY date ASC
    """, (stock_id, start_date))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 指標計算（純函式，不依賴實例）────────────────────────

def calc_ma(closes: list, period: int) -> list:
    result = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        result.append(sum(closes[i - period + 1 : i + 1]) / period)
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
        k_val = rsv_list[0]
        k.append(k_val)
        d.append(k_val)
        for i in range(1, len(rsv_list)):
            k_val = (2/3) * k[-1] + (1/3) * rsv_list[i]
            d_val = (2/3) * d[-1] + (1/3) * k_val
            k.append(k_val)
            d.append(d_val)
    return k, d


def calc_macd(closes, fast=12, slow=26, signal=9):
    def ema(cols, p):
        k = 2 / (p + 1)
        res = [None] * (p - 1)
        res.append(sum(cols[:p]) / p)
        for i in range(p, len(cols)):
            res.append(cols[i] * k + res[-1] * (1 - k))
        return res
    ef = ema(closes, fast)
    es = ema(closes, slow)
    dif = [None if ef[i] is None or es[i] is None else ef[i] - es[i] for i in range(len(closes))]
    dea = ema([(x or 0) for x in dif], signal)
    macd_bar = [None if dif[i] is None else 2 * (dif[i] - dea[i]) for i in range(len(dif))]
    return dif, dea, macd_bar


def calc_rsi(closes, period=14):
    result = [None] * (period)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    if len(gains) < period:
        return result
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    return result


def indicators_at(data: list, idx: int):
    """計算到 idx 為止的所有指標（只用 idx 之前的資料）"""
    lookback = 120
    start = max(0, idx - lookback)
    window = data[start:idx + 1]
    if len(window) < 30:
        return None

    closes = [d["close"] for d in window]
    highs  = [d["high"]  for d in window]
    lows   = [d["low"]   for d in window]

    ma5   = calc_ma(closes, 5)
    ma20  = calc_ma(closes, 20)
    ma60  = calc_ma(closes, 60)
    k, d  = calc_kd(highs, lows, closes)
    dif, dea, macd_bar = calc_macd(closes)
    rsi   = calc_rsi(closes)

    def g(lst):  # get latest non-None
        for x in reversed(lst):
            if x is not None:
                return x
        return None

    return {
        "close": closes[-1],
        "date":  window[-1]["date"],
        "MA5":   g(ma5), "MA20":  g(ma20), "MA60":  g(ma60),
        "K":     g(k),   "D":      g(d),
        "DIF":   g(dif), "DEA":    g(dea),  "MACD_Bar": g(macd_bar),
        "RSI":   g(rsi),
    }


# ── 策略定義 ─────────────────────────────────────────────

class Strategies:
    """策略庫"""

    @staticmethod
    def kd_gold_cross(ind) -> bool:
        """KD 黃金交叉（K從下方穿越D）"""
        k, d = ind["K"], ind["D"]
        if k is None or d is None:
            return False
        # 需要前一根 K < D，前當根 K > D（由外層的 prev 判斷）
        return True  # 標記為 KD_GOLD，需搭配 prev 判斷

    @staticmethod
    def kd_low_gold(ind) -> bool:
        """KD 低檔黃金交叉（K<30 時黃金交叉）"""
        k, d = ind["K"], ind["D"]
        return k is not None and d is not None and k > d and k < 30

    @staticmethod
    def macd_bull(ind) -> bool:
        """MACD 多頭（DIF > DEA 且柱狀圖正）"""
        dif, dea, bar = ind["DIF"], ind["DEA"], ind["MACD_Bar"]
        return dif is not None and dea is not None and bar is not None and dif > dea and bar > 0

    @staticmethod
    def ma_bull(ind) -> bool:
        """均線多頭排列（MA5 > MA20 > MA60）"""
        ma5, ma20, ma60 = ind["MA5"], ind["MA20"], ind["MA60"]
        return ma5 is not None and ma20 is not None and ma60 is not None and ma5 > ma20 > ma60

    @staticmethod
    def rsi_oversold(ind) -> bool:
        """RSI 超賣（<35）"""
        rsi = ind["RSI"]
        return rsi is not None and rsi < 35


# ── 回測核心 ─────────────────────────────────────────────

def backtest(strategy_name: str, stock_id: str, start_date: str,
             stop_loss_pct: float = 0.07,
             take_profit_pct: float = 0.15,
             max_hold_days: int = 20,
             slippage_pct: float = 0.002) -> dict:
    """
    單一策略回測

    參數：
      stop_loss_pct      停損%（預設7%）
      take_profit_pct    停利%（預設15%）
      max_hold_days      最長持有天數
      slippage_pct       滑價%（預設0.2%）
    """

    data = get_adjusted_prices(stock_id, start_date)
    if len(data) < 60:
        return {"error": f"資料不足（{len(data)}筆），需要至少60筆"}

    strategy_fn = {
        "kd_cross":      Strategies.kd_low_gold,
        "macd_bull":     Strategies.macd_bull,
        "ma_bull":       Strategies.ma_bull,
        "rsi_oversold":  Strategies.rsi_oversold,
        "all":           None,
    }.get(strategy_name)

    if strategy_fn is None and strategy_name != "all":
        return {"error": f"未知策略：{strategy_name}"}

    trades = []
    position = None  # {'entry_date','entry_idx','entry_price','shares'}

    i = 1  # 從第2根開始（有前一筆可以比較交叉）
    while i < len(data):
        ind = indicators_at(data, i)
        if ind is None:
            i += 1
            continue

        prev_ind = indicators_at(data, i - 1)
        if prev_ind is None:
            i += 1
            continue

        # 進場訊號判定
        if position is None:
            if strategy_name == "all":
                triggered = (Strategies.kd_low_gold(ind) or
                             Strategies.macd_bull(ind) or
                             Strategies.ma_bull(ind))
            else:
                # KD黃金交叉特殊判斷（需要對比前後）
                if strategy_name == "kd_cross":
                    k_cur, d_cur = ind["K"], ind["D"]
                    k_prev, d_prev = prev_ind["K"], prev_ind["D"]
                    triggered = (k_cur is not None and d_cur is not None and
                                k_prev is not None and d_prev is not None and
                                k_prev <= d_prev and k_cur > d_cur and k_cur < 60)
                else:
                    triggered = strategy_fn(ind)

            if triggered:
                entry_price = ind["close"] * (1 + slippage_pct)  # ，假設滑價
                position = {
                    "entry_date":  ind["date"],
                    "entry_idx":   i,
                    "entry_price": entry_price,
                    "signal":      strategy_name,
                    "reason":      f"{ind['date']} {stock_id} 進場",
                }

        # 持有中 → 檢查停損/停利/到期
        else:
            exit_reason = None
            hold_days = i - position["entry_idx"]
            current_price = data[i]["close"]

            pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

            # 停損
            if pnl_pct <= -stop_loss_pct:
                exit_reason = "STOP_LOSS"
            # 停利
            elif pnl_pct >= take_profit_pct:
                exit_reason = "TAKE_PROFIT"
            # 持有期滿
            elif hold_days >= max_hold_days:
                exit_reason = "TIME_UP"

            if exit_reason:
                exit_price = current_price * (1 - slippage_pct)
                trades.append({
                    "stock_id":    stock_id,
                    "entry_date":  position["entry_date"],
                    "entry_price": position["entry_price"],
                    "exit_date":   data[i]["date"],
                    "exit_price":  exit_price,
                    "pnl_pct":     round((exit_price - position["entry_price"]) / position["entry_price"] * 100, 2),
                    "hold_days":   hold_days,
                    "exit_reason": exit_reason,
                    "signal":      position["signal"],
                })
                position = None

        i += 1

    # 若持有到最後一天仍未出廠，記為未實現
    if position is not None:
        last_close = data[-1]["close"]
        pnl_pct = (last_close - position["entry_price"]) / position["entry_price"] * 100
        trades.append({
            "stock_id":    stock_id,
            "entry_date":  position["entry_date"],
            "entry_price": position["entry_price"],
            "exit_date":   data[-1]["date"],
            "exit_price":  last_close,
            "pnl_pct":     round(pnl_pct, 2),
            "hold_days":   len(data) - 1 - position["entry_idx"],
            "exit_reason": "STILL_HOLDING",
            "signal":      position["signal"],
        })

    return compute_stats(trades, stock_id, strategy_name, data)


def compute_stats(trades: list, stock_id: str, strategy_name: str, data: list) -> dict:
    """計算績效統計"""
    if not trades:
        return {
            "stock_id": stock_id,
            "strategy": strategy_name,
            "trades": [],
            "stats": {
                "total_trades": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "max_drawdown": 0,
                "total_return": 0,
            }
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # 累計曲線（簡單）
    equity = [100.0]
    peak = 100.0
    max_dd = 0.0
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
        peak = max(peak, equity[-1])
        dd = (peak - equity[-1]) / peak * 100
        max_dd = max(max_dd, dd)

    total_return = (equity[-1] / equity[0] - 1) * 100

    stats = {
        "total_trades": len(trades),
        "win_rate":     round(len(wins) / len(trades) * 100, 1),
        "avg_pnl":       round(sum(pnls) / len(pnls), 2),
        "avg_win":       round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":      round(sum(losses) / len(losses), 2) if losses else 0,
        "max_drawdown":  round(max_dd, 2),
        "total_return":  round(total_return, 2),
        "avg_hold_days": round(sum(t["hold_days"] for t in trades) / len(trades), 1),
    }

    return {
        "stock_id": stock_id,
        "strategy": strategy_name,
        "trades": trades,
        "stats": stats,
    }


# ── 報告產出 ─────────────────────────────────────────────

def print_backtest_report(result: dict):
    if "error" in result:
        print(f"❌ {result['error']}")
        return

    s = result["stats"]
    trades = result["trades"]

    print(f"\n{'='*55}")
    print(f"【Stephanie 回測報告】{result['stock_id']} × {result['strategy']}")
    print(f"{'='*55}")
    print(f"  總交易次數  ：{s['total_trades']} 筆")
    print(f"  勝率        ：{s['win_rate']}%")
    print(f"  平均報酬    ：{s['avg_pnl']}%")
    print(f"  平均獲利    ：{s['avg_win']}%")
    print(f"  平均虧損    ：{s['avg_loss']}%")
    print(f"  最大區間虧損：{s['max_drawdown']}%")
    print(f"  總報酬率    ：{s['total_return']}%")
    print(f"  平均持有天數：{s['avg_hold_days']} 天")
    print(f"{'='*55}")

    if trades:
        print("\n近10筆交易：")
        print(f"  {'進場日':<12} {'進場價':>8} {'出場日':<12} {'出場價':>8} {'報酬%':>7} {'持有天':>6} {'原因'}")
        print("  " + "-" * 65)
        for t in trades[-10:]:
            print(f"  {t['entry_date']:<12} {t['entry_price']:>8.2f} {t['exit_date']:<12} "
                  f"{t['exit_price']:>8.2f} {t['pnl_pct']:>+7.2f}% {t['hold_days']:>6} {t['exit_reason']}")


# ── 主程式 ───────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回測引擎")
    parser.add_argument("--stock", type=str, default="4967", help="股票代碼（多檔用空白分隔）")
    parser.add_argument("--strategy", type=str,
                        choices=["kd_cross","kd_low","macd_bull","ma_bull","rsi_oversold","all"],
                        default="kd_cross")
    parser.add_argument("--start", type=str, default="2025-01-01")
    parser.add_argument("--stop-loss", type=float, default=0.07)
    parser.add_argument("--take-profit", type=float, default=0.15)
    parser.add_argument("--max-hold", type=int, default=20)
    args = parser.parse_args()

    stocks = args.stock.split()
    for sid in stocks:
        result = backtest(
            strategy_name=args.strategy,
            stock_id=sid,
            start_date=args.start,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
            max_hold_days=args.max_hold,
        )
        print_backtest_report(result)
