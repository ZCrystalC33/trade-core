"""
Trade Core Dashboard — 系統監控面板

顯示：
- Signal 統計（產出、執行率、勝率）
- 維度表現（各維度的預測準確度）
- Evolution 狀態（上次進化時間、調整內容）
- 市場體制（當前 BULL/BEAR/NEUTRAL）
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
WEIGHTS_FILE = Path(__file__).parent.parent / "data" / "evolved_weights.json"


def get_signal_stats(days: int = 7) -> Dict:
    """取得訊號統計"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    # 總訊號數
    cur.execute("""
        SELECT COUNT(*) as total
        FROM trade_signals
        WHERE created_at >= ?
    """, (cutoff,))
    total = cur.fetchone()["total"]
    
    # 已執行
    cur.execute("""
        SELECT COUNT(*) as executed
        FROM trade_signals ts
        WHERE ts.created_at >= ?
          AND EXISTS (SELECT 1 FROM trades t WHERE t.signal_id = ts.id)
    """, (cutoff,))
    executed = cur.fetchone()["executed"]
    
    # 本週新訊號（從 daily_top30 或 scanner）
    cur.execute("""
        SELECT signal_source, COUNT(*) as cnt
        FROM trade_signals
        WHERE created_at >= ?
        GROUP BY signal_source
    """, (cutoff,))
    by_source = {r["signal_source"]: r["cnt"] for r in cur.fetchall()}
    
    conn.close()
    
    return {
        "total": total,
        "executed": executed,
        "execution_rate": round(executed / total * 100, 1) if total > 0 else 0,
        "by_source": by_source
    }


def get_trade_stats(days: int = 30) -> Dict:
    """取得交易統計"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            AVG(realized_pnl_pct) as avg_pnl,
            SUM(realized_pnl_pct) as total_pnl,
            AVG(hold_days) as avg_hold_days
        FROM trades
        WHERE status = 'CLOSED'
          AND created_at >= ?
          AND realized_pnl_pct IS NOT NULL
    """, (cutoff,))
    
    row = cur.fetchone()
    conn.close()
    
    total = row["total"] or 0
    wins = row["wins"] or 0
    
    return {
        "total_trades": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "avg_pnl": round(row["avg_pnl"] or 0, 3),
        "total_pnl": round(row["total_pnl"] or 0, 2),
        "avg_hold_days": round(row["avg_hold_days"] or 0, 1)
    }


def get_dimension_performance() -> Dict:
    """取得維度表現（從回測歷史推估）"""
    # 維度表現需要更多資料，這裡用占位實現
    # 完整版需要信號維度分數資料
    weights = _load_weights()
    
    return {
        "momentum": {"current_weight": weights.get("momentum", 0.25), "trend": "stable"},
        "technical": {"current_weight": weights.get("technical", 0.25), "trend": "stable"},
        "fund_flow": {"current_weight": weights.get("fund_flow", 0.20), "trend": "stable"},
        "liquidity": {"current_weight": weights.get("liquidity", 0.10), "trend": "stable"},
        "volatility": {"current_weight": weights.get("volatility", 0.05), "trend": "stable"},
        "leverage": {"current_weight": weights.get("leverage", 0.05), "trend": "stable"},
        "industry": {"current_weight": weights.get("industry", 0.05), "trend": "stable"}
    }


def _load_weights() -> Dict:
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE) as f:
            return json.load(f)
    return {
        "momentum": 0.25,
        "technical": 0.25,
        "fund_flow": 0.20,
        "liquidity": 0.10,
        "volatility": 0.05,
        "leverage": 0.05,
        "industry": 0.05
    }


def get_evolution_status() -> Dict:
    """取得 Evolution 狀態"""
    weights = _load_weights()
    
    # 嘗試從 evolution engine 讀取上次執行時間
    # 這裡用簡化實現
    return {
        "last_evolution": "2026-04-22 11:30",  # placeholder
        "current_weights": weights,
        "regime_action": "MAINTAIN"
    }


def get_market_regime() -> Dict:
    """取得當前市場體制"""
    # 從 Jin10 macro sentiment 讀取
    try:
        from jin10 import Jin10Client
        jc = Jin10Client()
        score = jc.get_macro_sentiment()
        flag = jc.check_macro_threshold(score)
        
        if score is None:
            return {"regime": "UNKNOWN", "score": None, "flag": None}
        
        if score >= 0.6:
            regime = "BULL"
        elif score <= 0.4:
            regime = "BEAR"
        else:
            regime = "NEUTRAL"
        
        return {"regime": regime, "score": round(score, 3), "flag": flag}
    except:
        return {"regime": "UNKNOWN", "score": None, "flag": None, "note": "Jin10 unavailable"}


def generate_dashboard_text() -> str:
    """生成 Dashboard 文字報告"""
    signal_stats = get_signal_stats()
    trade_stats = get_trade_stats()
    dim_perf = get_dimension_performance()
    evo_status = get_evolution_status()
    regime = get_market_regime()
    
    lines = []
    lines.append("=" * 55)
    lines.append("【Trade Core 系統監控面板】")
    lines.append(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 55)
    
    # 市場體制
    lines.append("\n📊 市場體制")
    lines.append(f"  目前：{regime['regime']}")
    if regime.get("score"):
        lines.append(f"  分數：{regime['score']}（閾值 {regime.get('flag', 'N/A')}）")
    
    # Signal 統計
    lines.append("\n📈 Signal 統計（近7天）")
    lines.append(f"  總訊號：{signal_stats['total']}")
    lines.append(f"  已執行：{signal_stats['executed']}（{signal_stats['execution_rate']}%）")
    if signal_stats["by_source"]:
        for src, cnt in signal_stats["by_source"].items():
            lines.append(f"    - {src}: {cnt}")
    
    # 交易統計
    lines.append("\n💰 交易統計（近30天）")
    lines.append(f"  總交易：{trade_stats['total_trades']}")
    lines.append(f"  勝率：{trade_stats['win_rate']}%")
    lines.append(f"  平均報酬：{trade_stats['avg_pnl']:+.3f}%")
    lines.append(f"  總損益：{trade_stats['total_pnl']:+.2f}%")
    lines.append(f"  平均持有：{trade_stats['avg_hold_days']} 天")
    
    # Evolution 狀態
    lines.append("\n🔄 Evolution 狀態")
    lines.append(f"  上次進化：{evo_status['last_evolution']}")
    lines.append(f"  市場策略：{evo_status['regime_action']}")
    lines.append("  維度權重：")
    for dim, data in evo_status["current_weights"].items():
        lines.append(f"    - {dim}: {data:.1%}")
    
    # 維度表現
    lines.append("\n📉 維度表現")
    for dim, data in dim_perf.items():
        w = data["current_weight"]
        trend = data["trend"]
        trend_icon = "→" if trend == "stable" else ("↑" if "up" in trend else "↓")
        lines.append(f"  {dim:<12} {w:.1%} {trend_icon}")
    
    lines.append("\n" + "=" * 55)
    
    return "\n".join(lines)


def generate_dashboard_json() -> Dict:
    """生成 Dashboard JSON 格式"""
    return {
        "timestamp": datetime.now().isoformat(),
        "market_regime": get_market_regime(),
        "signal_stats": get_signal_stats(),
        "trade_stats": get_trade_stats(),
        "dimension_performance": get_dimension_performance(),
        "evolution_status": get_evolution_status()
    }


# CLI interface
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Trade Core Dashboard")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--days", type=int, default=7, help="Stats period in days")
    args = parser.parse_args()
    
    if args.json:
        print(json.dumps(generate_dashboard_json(), indent=2, default=str))
    else:
        print(generate_dashboard_text())


if __name__ == "__main__":
    main()
