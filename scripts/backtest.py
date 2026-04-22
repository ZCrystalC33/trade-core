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

 交易成本說明（台股預設）：
   - 單邊手續費  0.5%，來回 1.0%
   - 進場價 × 1.005 = 真實成本價（跌破此值即虧損）
   - 停利 15%（毛利）= 淨利約 14%（扣除來回 1%）
   - 停損門檻以進場價為基準，但實際虧損已內含進場手續費
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import indicators_lib as il
import cost_model as cm

try:
    import jin10_client as jc
    JIN10_AVAILABLE = True
except ImportError:
    JIN10_AVAILABLE = False

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

# ── 宏觀參數 ─────────────────────────────────────────────
MACRO_BULL_THRESHOLD = 55.0   # 宏觀分數 >= 此值才允許做多
MACRO_BEAR_THRESHOLD = 45.0   # 宏觀分數 <= 此值才允許做空


# ── 歷史資料讀取 ──────────────────────────────────────────

def get_adjusted_prices(stock_id: str, start_date: str = "2020-01-01") -> pd.DataFrame:
    """
    優先讀取還原價格，若無則用原始價格。
    返回含 open/high/low/close/volume 的 DataFrame（由舊到新）。
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
        return pd.DataFrame([dict(r) for r in rows])

    # 沒有還原價格，用原始價格
    cursor.execute("""
        SELECT date, open, high, low, close, close as adj_close, volume
        FROM daily_price
        WHERE stock_id = ? AND date >= ?
        ORDER BY date ASC
    """, (stock_id, start_date))
    rows = cursor.fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows])


# ── 指標封裝（落後計算，避免偷價）────────────────────────

def indicators_at(df: pd.DataFrame, idx: int, lookback: int = 120) -> dict:
    """
    取到 df[idx] 為止的歷史視窗，計算落後指標，回傳最後一筆 dict。
    實現方式：複製視窗 → add_all_indicators → 取最後一筆 → lag_indicators 落後1筆。
    """
    start = max(0, idx - lookback)
    window = df.iloc[start:idx + 1].copy()
    if len(window) < 30:
        return None

    df_ind = il.add_all_indicators(window)
    df_lag = il.lag_indicators(df_ind, n=1)

    # 取倒數第2筆（即 idx-1 位置，確保不用當根收盤價）
    if len(df_lag) < 2:
        return None
    row = df_lag.iloc[-2]  # idx-1 的落後值

    return {
        "close":  row["close"],
        "date":   row["date"],
        "MA5":    il.get_valid(row["MA5"]) if "MA5" in row else None,
        "MA20":   il.get_valid(row["MA20"]) if "MA20" in row else None,
        "MA60":   il.get_valid(row["MA60"]) if "MA60" in row else None,
        "K":      il.get_valid(row["K"]) if "K" in row else None,
        "D":      il.get_valid(row["D"]) if "D" in row else None,
        "DIF":    il.get_valid(row["DIF"]) if "DIF" in row else None,
        "DEA":    il.get_valid(row["DEA"]) if "DEA" in row else None,
        "MACD_Bar": il.get_valid(row["MACD_Bar"]) if "MACD_Bar" in row else None,
        "RSI":    il.get_valid(row["RSI"]) if "RSI" in row else None,
        "BB_Upper": il.get_valid(row["BB_Upper"]) if "BB_Upper" in row else None,
        "BB_MA":  il.get_valid(row["BB_MA"]) if "BB_MA" in row else None,
        "BB_Lower": il.get_valid(row["BB_Lower"]) if "BB_Lower" in row else None,
    }


# ── 策略定義 ─────────────────────────────────────────────

class Strategies:
    """策略庫"""

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
             slippage_pct: float = 0.002,
             market: str = "TW") -> dict:
    """
    單一策略回測

    參數：
      stop_loss_pct      停損%（預設7%）— 以進場價為基準的毛跌幅門檻
      take_profit_pct    停利%（預設15%）— 以進場價為基準的目標毛利率
      max_hold_days      最長持有天數
      slippage_pct       滑價%（預設0.2%）
      market             市場別（"TW"台股/"US"美股/"CRYPTO"加密幣，預設TW）

    成本模型（台股預設）：
      - 進場真實成本價 = 進場價 × 1.005
        → 跌破此價即已虧損（含進場手續費）
      - 停損觸發門檻 = 進場價下跌 stop_loss_pct
        → 到出場時再扣出場手續費，實際虧損 = 毛損 + 0.5%
      - 停利觸發門檻 = 進場價上漲 (take_profit_pct + 來回費率)
        → 毛利需先覆蓋來回 1% 成本，才能拿到目標淨利
      - 最終 pnl_pct 以 net_pnl_pct() 回報，已扣除來回手續費
    """

    df = get_adjusted_prices(stock_id, start_date)
    if len(df) < 60:
        return {"error": f"資料不足（{len(df)}筆），需要至少60筆"}

    # 建立成本模型（依市場別）
    cost = cm.CostModel(market)
    # 停利觸發門檻調整：毛利需先覆蓋來回成本，才能實現目標淨利
    gross_take_profit_pct = cost.adjusted_take_profit_pct(take_profit_pct)

    strategy_fn = {
        "kd_cross":     Strategies.kd_low_gold,
        "macd_bull":    Strategies.macd_bull,
        "ma_bull":      Strategies.ma_bull,
        "rsi_oversold": Strategies.rsi_oversold,
        "all":          None,
    }.get(strategy_name)
    if strategy_fn is None and strategy_name != "all":
        return {"error": f"未知策略：{strategy_name}"}

    trades = []
    position = None  # {'entry_date','entry_idx','entry_price','cost_basis','shares'}

    i = 1  # 從第2根開始（有前一筆可以比較交叉）
    while i < len(df):
        # Cache indicators to avoid recomputation (Pattern: Select - memoize promise)
        if i == start_idx + 1:
            # First iteration: compute both current and previous
            prev_ind = indicators_at(df, i - 1)
            ind = indicators_at(df, i)
        else:
            # Subsequent: reuse previous ind as prev_ind, compute only current
            prev_ind = _cached_ind
            ind = indicators_at(df, i)
        _cached_ind = ind
        
        if ind is None:
            i += 1
            continue

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
                # ── 宏觀維度過濾 ────────────────────────────────
                # 只在 Jin10 可用時才應用，避免影響無法連線時的原有邏輯
                macro_filter_passed = True
                if JIN10_AVAILABLE:
                    try:
                        # Cache macro sentiment for backtest run (avoid per-bar API calls)
                        if _macro_cached["score"] is None:
                            _macro_cached["score"] = jc.get_macro_sentiment()
                            _macro_cached["flag"] = jc.check_macro_threshold(
                                _macro_cached["score"],
                                bull_threshold=MACRO_BULL_THRESHOLD,
                                bear_threshold=MACRO_BEAR_THRESHOLD,
                            )
                        macro_score = _macro_cached["score"]
                        macro_flag = _macro_cached["flag"]
                        # LONG 訊號需要宏觀 BULL，SHORT 訊號需要 BEAR
                        # 多頭策略（kd_cross, macd_bull, ma_bull）預設是 LONG
                        # 若宏觀不支持則跳過這筆進場
                        if strategy_name in ("kd_cross", "macd_bull", "ma_bull", "all"):
                            if macro_flag != "BULL":
                                macro_filter_passed = False
                    except Exception as e:
                        # 宏觀API失效時，放行所有進場（不鎖死系統）
                        import logging
                        logging.warning(f"Macro API failed: {e}")
                        macro_score = None
                        macro_flag = "UNKNOWN"
                else:
                    macro_score = None
                    macro_flag = "N/A"

                if not macro_filter_passed:
                    i += 1
                    continue  # 宏觀不支持，跳過此次進場

                # 進場價：信號收盤價 + 滑價（下一根開盤的近似估計）
                entry_price = ind["close"] * (1 + slippage_pct)
                # 真實成本價：進場價 + 單邊進場手續費
                # 跌破此價即表示已開始虧損（含進場費用）
                cost_basis = cost.cost_basis(entry_price)
                position = {
                    "entry_date":  ind["date"],
                    "entry_idx":   i,
                    "entry_price": entry_price,
                    "cost_basis":  cost_basis,  # 進場價 × (1 + one_way_rate)
                    "signal":      strategy_name,
                    "reason":      f"{ind['date']} {stock_id} 進場",
                    "macro_score": macro_score,
                    "macro_flag":  macro_flag,
                }

        # 持有中 → 檢查停損/停利/到期
        else:
            exit_reason = None
            hold_days = i - position["entry_idx"]
            current_price = df.iloc[i]["close"]

            # 以進場價計算毛損益率（含進場滑價，不含出場合約）
            # entry_price 已含進場滑價，current_price 為原始收盤價
            gross_pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

            # 停損判斷：
            #   以進場價為基準的毛跌幅 >= stop_loss_pct 時出場。
            #   注意：由於進場時已付 one_way_rate，加上出場的 one_way_rate，
            #   實際淨虧損 = 毛損 + 來回費率（比帳面更大）。
            if gross_pnl_pct <= -stop_loss_pct:
                exit_reason = "STOP_LOSS"
            # 停利判斷：
            #   毛利需達到 gross_take_profit_pct（= 目標淨利 + 來回費率）才出場，
            #   確保出場後扣除來回手續費仍能拿到目標淨利。
            elif gross_pnl_pct >= gross_take_profit_pct:
                exit_reason = "TAKE_PROFIT"
            # 持有期滿
            elif hold_days >= max_hold_days:
                exit_reason = "TIME_UP"

            if exit_reason:
                exit_price = current_price * (1 - slippage_pct)
                net_pnl = cost.net_pnl_pct(position["entry_price"], exit_price)
                trades.append({
                    "stock_id":    stock_id,
                    "entry_date":  position["entry_date"],
                    "entry_price": position["entry_price"],
                    "cost_basis":  position["cost_basis"],
                    "exit_date":   df.iloc[i]["date"],
                    "exit_price":  exit_price,
                    "pnl_pct":     round(net_pnl, 2),
                    "hold_days":   hold_days,
                    "exit_reason": exit_reason,
                    "signal":      position["signal"],
                    "macro_score": position.get("macro_score"),
                    "macro_flag":  position.get("macro_flag"),
                })
                position = None

        i += 1

    # 若持有到最後一天仍未出廠，記為未實現（以收盤價估算淨損益）
    if position is not None:
        last_close = df.iloc[-1]["close"]
        net_pnl = cost.net_pnl_pct(position["entry_price"], last_close)
        trades.append({
            "stock_id":    stock_id,
            "entry_date":  position["entry_date"],
            "entry_price": position["entry_price"],
            "cost_basis":  position["cost_basis"],
            "exit_date":   df.iloc[-1]["date"],
            "exit_price":  last_close,
            "pnl_pct":     round(net_pnl, 2),
            "hold_days":   len(df) - 1 - position["entry_idx"],
            "exit_reason": "STILL_HOLDING",
            "signal":      position["signal"],
        })

    return compute_stats(trades, stock_id, strategy_name, df)


def compute_stats(trades: list, stock_id: str, strategy_name: str, df: pd.DataFrame) -> dict:
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

    print(f"\n{'='*60}")
    print(f"【Stephanie 回測報告】{result['stock_id']} × {result['strategy']}")
    print(f"{'='*60}")
    print(f"  總交易次數  ：{s['total_trades']} 筆")
    print(f"  勝率        ：{s['win_rate']}%")
    print(f"  平均報酬    ：{s['avg_pnl']}%（已扣手續費）")
    print(f"  平均獲利    ：{s['avg_win']}%")
    print(f"  平均虧損    ：{s['avg_loss']}%")
    print(f"  最大區間虧損：{s['max_drawdown']}%")
    print(f"  總報酬率    ：{s['total_return']}%")
    print(f"  平均持有天數：{s.get('avg_hold_days', 0)} 天")
    print(f"{'='*60}")

    if trades:
        print("\n近10筆交易（pnl_pct 已扣來回手續費）：")
        print(f"  {'進場日':<12} {'進場價':>8} {'成本價':>8} {'出場日':<12} {'出場價':>8} {'淨利%':>7} {'持有天':>6} {'宏觀':>6} {'原因'}")
        print("  " + "-" * 85)
        for t in trades[-10:]:
            cb = t.get("cost_basis", t["entry_price"])
            macro = f"{t.get('macro_flag','?')}"
            if t.get('macro_score') is not None:
                macro = f"{t.get('macro_flag','?')}:{t.get('macro_score',0):.0f}"
            print(f"  {t['entry_date']:<12} {t['entry_price']:>8.2f} {cb:>8.2f} {t['exit_date']:<12} "
                  f"{t['exit_price']:>8.2f} {t['pnl_pct']:>+7.2f}% {t['hold_days']:>6} {macro:>8} {t['exit_reason']}")


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
    parser.add_argument("--market", type=str, default="TW",
                        choices=["TW", "US", "CRYPTO"],
                        help="市場別（TW台股/US美股/CRYPTO加密幣，預設TW）")
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
            market=args.market,
        )
        print_backtest_report(result)
