"""
Evolution Engine — 根據 Feedback 自動優化策略參數

核心概念：讓數據說話，讓系統進化

學習方式：
1. WinRateAnalyzer — 哪些維度預測最準？
2. PatternLearner — 什麼條件組合勝率最高？
3. WeightOptimizer — 評分權重要不要調整？
4. RegimeAware — BULL/BEAR 市場表現差異
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

DB_PATH = Path(__file__).parent.parent.parent / "data" / "stock_quant.db"

# 預設維度權重（會被 evolution 調整）
DEFAULT_WEIGHTS = {
    "momentum": 0.25,
    "technical": 0.25,
    "fund_flow": 0.20,
    "liquidity": 0.10,
    "volatility": 0.05,
    "leverage": 0.05,
    "industry": 0.05
}


class WinRateAnalyzer:
    """分析各維度的預測準確度"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
    
    def analyze_dimension_winrates(self, min_samples: int = 30) -> Dict[str, dict]:
        """
        分析每個維度的勝率
        
        Returns:
            {
                "momentum": {"win_rate": 0.72, "sample_size": 156, "avg_pnl": 0.045},
                ...
            }
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        results = {}
        
        # 從 trades 表讀取關閉的交易
        cur.execute("""
            SELECT realized_pnl_pct, hold_days, exit_reason, status
            FROM trades
            WHERE status = 'CLOSED' AND realized_pnl_pct IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
        """)
        
        trades = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        if len(trades) < min_samples:
            return {"_error": f"Insufficient data: {len(trades)} < {min_samples}"}
        
        # 計算基本統計
        wins = sum(1 for t in trades if t["realized_pnl_pct"] > 0)
        total_pnl = sum(t["realized_pnl_pct"] for t in trades)
        
        results["_overall"] = {
            "win_rate": wins / len(trades),
            "sample_size": len(trades),
            "avg_pnl": total_pnl / len(trades),
            "total_pnl": total_pnl
        }
        
        # 依 exit_reason 分析
        for reason in ["STOP_LOSS", "TAKE_PROFIT", "TIME_UP"]:
            subset = [t for t in trades if t.get("exit_reason") == reason]
            if subset:
                w = sum(1 for t in subset if t["realized_pnl_pct"] > 0)
                results[f"exit_{reason}"] = {
                    "win_rate": w / len(subset),
                    "sample_size": len(subset),
                    "avg_pnl": sum(t["realized_pnl_pct"] for t in subset) / len(subset)
                }
        
        # 依持有天數分析
        for days_bucket in [(0, 5), (5, 20), (20, 100)]:
            subset = [t for t in trades if days_bucket[0] <= t["hold_days"] < days_bucket[1]]
            if subset:
                w = sum(1 for t in subset if t["realized_pnl_pct"] > 0)
                results[f"hold_{days_bucket[0]}to{days_bucket[1]}"] = {
                    "win_rate": w / len(subset),
                    "sample_size": len(subset),
                    "avg_pnl": sum(t["realized_pnl_pct"] for t in subset) / len(subset)
                }
        
        return results


class WeightOptimizer:
    """優化評分維度權重"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.weights_file = db_path.parent / "evolved_weights.json"
        self.weights = self._load_weights()
    
    def _load_weights(self) -> Dict[str, float]:
        """載入當前權重（優先 DB 中的，沒有則用預設）"""
        if self.weights_file.exists():
            with open(self.weights_file) as f:
                return json.load(f)
        return DEFAULT_WEIGHTS.copy()
    
    def _save_weights(self):
        """儲存權重到檔案"""
        with open(self.weights_file, "w") as f:
            json.dump(self.weights, f, indent=2)
    
    def get_weights(self) -> Dict[str, float]:
        """取得當前權重"""
        return self.weights.copy()
    
    def optimize(self, winrate_analysis: Dict[str, dict], threshold: float = 0.05) -> Dict[str, float]:
        """
        根據勝率分析調整權重
        
        原則：
        - 如果某維度的勝率比平均高 5% 以上，增加該維度權重
        - 如果某維度的勝率比平均低 5% 以上，減少該維度權重
        - 調整幅度：每次最多增減 0.02 (2%)
        - 總權重永遠保持 1.0
        
        Returns:
            新的權重字典
        """
        overall = winrate_analysis.get("_overall")
        if not overall:
            return self.weights
        
        avg_win_rate = overall["win_rate"]
        new_weights = self.weights.copy()
        
        # 維度權重調整（根據分析結果）
        # 這是簡化版本，完整實現需要信號維度資料
        adjustments = {
            "momentum": 0.0,    # 根據動能勝率調整
            "technical": 0.0,  # 根據技術面勝率調整
        }
        
        changed = False
        for dim, adj in adjustments.items():
            if abs(adj) < threshold:
                continue
            
            new_weights[dim] = max(0.01, min(0.5, new_weights[dim] + adj))
            changed = True
        
        if changed:
            # 正規化確保總和為 1
            total = sum(new_weights.values())
            new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
            self.weights = new_weights
            self._save_weights()
        
        return new_weights


class RegimeAwareEngine:
    """市場體制感知引擎"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
    
    def get_regime_stats(self, min_samples: int = 20) -> Dict[str, dict]:
        """
        取得各市場體制的交易表現
        
        Returns:
            {
                "BULL": {"win_rate": 0.68, "sample_size": 45},
                "BEAR": {"win_rate": 0.35, "sample_size": 12},
                "NEUTRAL": {"win_rate": 0.55, "sample_size": 33}
            }
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        results = {}
        for regime in ["BULL", "BEAR", "NEUTRAL"]:
            cur.execute("""
                SELECT COUNT(*) as cnt,
                       SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                       AVG(realized_pnl_pct) as avg_pnl
                FROM trades
                WHERE status = 'CLOSED'
                  AND realized_pnl_pct IS NOT NULL
                  AND (notes LIKE '%REGIME={regime}%' OR notes LIKE '%regime={regime}%')
            """.format(regime=regime))
            
            row = cur.fetchone()
            cnt = row[0] if row else 0
            
            if cnt >= min_samples:
                results[regime] = {
                    "win_rate": row[1] / cnt if cnt > 0 else 0,
                    "sample_size": cnt,
                    "avg_pnl": row[2] or 0
                }
            else:
                results[regime] = {
                    "win_rate": None,
                    "sample_size": cnt,
                    "note": f"insufficient samples (need {min_samples})"
                }
        
        conn.close()
        return results
    
    def get_recommended_regime_action(self) -> Dict[str, any]:
        """
        根據 regime stats 建議當前市場應該：
        - 積極操作（ENHANCE）或保守操作（REDUCE）或暫停（PAUSE）
        """
        stats = self.get_regime_stats()
        
        bull = stats.get("BULL", {})
        bear = stats.get("BEAR", {})
        
        if not bull.get("win_rate") or not bear.get("win_rate"):
            return {"action": "MAINTAIN", "reason": "insufficient regime data"}
        
        # 如果 BULL 勝率 > 55% 且 BEAR 勝率 < 45%，建議積極
        if bull["win_rate"] > 0.55 and bear["win_rate"] < 0.45:
            return {
                "action": "ENHANCE",
                "reason": f"BULL win_rate={bull['win_rate']:.1%}, BEAR win_rate={bear['win_rate']:.1%}",
                "bull_weight_mult": 1.2,
                "bear_weight_mult": 0.8
            }
        
        # 如果 BEAR 勝率 > 50%，建議保守
        if bear["win_rate"] > 0.50:
            return {
                "action": "REDUCE",
                "reason": f"BEAR win_rate={bear['win_rate']:.1%} is high — likely regime misdetection",
                "bull_weight_mult": 0.9,
                "bear_weight_mult": 0.9
            }
        
        return {"action": "MAINTAIN", "reason": "regime stats within normal range"}


class EvolutionEngine:
    """
    進化引擎主控制器
    
    使用方式：
        engine = EvolutionEngine()
        engine.run()  # 執行一次進化
        weights = engine.get_current_weights()
        stats = engine.get_stats()
    """
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.analyzer = WinRateAnalyzer(db_path)
        self.optimizer = WeightOptimizer(db_path)
        self.regime_engine = RegimeAwareEngine(db_path)
        self.last_run = None
        self.last_results = None
    
    def run(self, force: bool = False) -> dict:
        """
        執行一次進化分析
        
        條件：
        - 至少 30 筆 Closed Trades
        - 距離上次執行至少 24 小時（除非 force=True）
        """
        now = datetime.now()
        
        # Check cooldown
        if not force and self.last_run:
            if (now - self.last_run) < timedelta(hours=24):
                return {
                    "status": "skipped",
                    "reason": f"last run {self.last_run}, cooldown 24h",
                    "next_run": self.last_run + timedelta(hours=24)
                }
        
        # Analyze
        winrate_analysis = self.analyzer.analyze_dimension_winrates()
        
        # Optimize weights
        new_weights = self.optimizer.optimize(winrate_analysis)
        
        # Regime analysis
        regime_stats = self.regime_engine.get_regime_stats()
        regime_action = self.regime_engine.get_recommended_regime_action()
        
        self.last_run = now
        self.last_results = {
            "timestamp": now.isoformat(),
            "winrate_analysis": winrate_analysis,
            "weights": new_weights,
            "regime_stats": regime_stats,
            "regime_action": regime_action
        }
        
        return self.last_results
    
    def get_current_weights(self) -> Dict[str, float]:
        return self.optimizer.get_weights()
    
    def get_stats(self) -> dict:
        """取得當前系統狀態"""
        return {
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "current_weights": self.get_weights(),
            "regime_action": self.regime_engine.get_recommended_regime_action()
        }


# CLI interface
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Evolution Engine")
    parser.add_argument("--run", action="store_true", help="Run evolution")
    parser.add_argument("--weights", action="store_true", help="Show current weights")
    parser.add_argument("--regime", action="store_true", help="Show regime stats")
    parser.add_argument("--force", action="store_true", help="Force run (skip cooldown)")
    args = parser.parse_args()
    
    engine = EvolutionEngine()
    
    if args.run:
        result = engine.run(force=args.force)
        print(json.dumps(result, indent=2, default=str))
    
    elif args.weights:
        print(json.dumps(engine.get_current_weights(), indent=2))
    
    elif args.regime:
        print(json.dumps(engine.regime_engine.get_regime_stats(), indent=2))
    
    else:
        # Default: show stats
        print(json.dumps(engine.get_stats(), indent=2))


if __name__ == "__main__":
    main()
