#!/usr/bin/env python3
"""
cost_model.py — 交易成本模型

支援市場：
  - 台股（TW）  ：單邊 0.5%，來回 1.0%
  - 美股（US）  ：單邊 0.1%，來回 0.2%
  - 加密幣（CRYPTO）：單邊 0.2%，來回 0.4%

使用範例：
    from cost_model import CostModel
    cm = CostModel("TW")

    # 來回成本金額
    print(cm.roundtrip_cost(100.0))   # 1.0

    # 真實成本價（進場後加上進場手續費）
    print(cm.cost_basis(100.0))       # 100.5

    # 最小獲利出場價（需覆蓋來回成本才不虧）
    print(cm.min_profit_exit(100.0))  # 101.0

    # 淨利潤率（已扣除來回成本）
    print(cm.net_pnl_pct(100.0, 115.0))  # 約 14.0%
"""

from __future__ import annotations

# 各市場單邊手續費率（買或賣各計一次）
_MARKET_ONE_WAY: dict[str, float] = {
    "TW":     0.005,   # 台股 0.5%
    "US":     0.001,   # 美股 0.1%
    "CRYPTO": 0.002,   # 加密幣 0.2%
}


class CostModel:
    """
    交易成本模型。

    Attributes:
        market      (str)  : 市場代碼（"TW" / "US" / "CRYPTO"）
        one_way_rate(float): 單邊手續費率
        roundtrip_rate (float): 來回手續費率（one_way * 2）
    """

    def __init__(self, market: str = "TW"):
        market = market.upper()
        if market not in _MARKET_ONE_WAY:
            raise ValueError(
                f"未知市場 '{market}'，請選擇：{list(_MARKET_ONE_WAY.keys())}"
            )
        self.market = market
        self.one_way_rate: float = _MARKET_ONE_WAY[market]
        self.roundtrip_rate: float = self.one_way_rate * 2

    # ── 成本計算 ──────────────────────────────────────────

    def one_way_cost(self, price: float) -> float:
        """單邊手續費金額（進場費 或 出場費）"""
        return price * self.one_way_rate

    def roundtrip_cost(self, price: float) -> float:
        """
        以進場價計算來回手續費金額。
        （實務近似值：以進場價估算來回總費用，保守略偏高）
        """
        return price * self.roundtrip_rate

    def cost_basis(self, entry_price: float) -> float:
        """
        真實成本價：進場價 × (1 + 單邊手續費率)。
        只要現價低於此值，就已處於虧損狀態。

        範例（台股）：進場 100 → 成本價 100.5
        """
        return entry_price * (1 + self.one_way_rate)

    def min_profit_exit(self, entry_price: float) -> float:
        """
        最小獲利出場價：現價須高於此值才能實現「毛利覆蓋成本」。
        計算方式：進場價 × (1 + 來回手續費率)。

        範例（台股）：進場 100 → 最低損益兩平出場價 101.0
        """
        return entry_price * (1 + self.roundtrip_rate)

    def net_pnl_pct(self, entry_price: float, exit_price: float) -> float:
        """
        計算扣除來回手續費後的淨損益率（%）。

        計算公式：
            gross_pnl = (exit_price - entry_price) / entry_price
            net_pnl   = gross_pnl - roundtrip_rate
            回傳 net_pnl * 100

        範例（台股）：進 100 出 115 → 毛利 15% - 成本 1% = 淨利 14%
        """
        gross = (exit_price - entry_price) / entry_price
        return (gross - self.roundtrip_rate) * 100

    def adjusted_stop_loss_pct(self, raw_stop_loss_pct: float) -> float:
        """
        考量成本後的實際停損觸發門檻。

        由於進場後真實成本價已高於進場價，
        若以進場價計算下跌 X% 為停損，
        實際虧損已包含 one_way_rate：
            實際觸發門檻 = raw_stop_loss_pct - one_way_rate

        使用者設定 7% 停損 → 股票只需下跌 6.5% 即觸發（台股）。
        回傳的是「相對進場價的觸發百分比（正數表示跌幅閾值）」。
        """
        return max(0.0, raw_stop_loss_pct - self.one_way_rate)

    def adjusted_take_profit_pct(self, raw_take_profit_pct: float) -> float:
        """
        考量成本後的實際停利觸發門檻（毛利%）。

        設定 15% 停利 → 需先覆蓋來回 1% 成本，
        所以股票需漲到毛利 16% 才能拿到淨利 15%。
        回傳「相對進場價的觸發百分比（毛利觸發點）」。
        """
        return raw_take_profit_pct + self.roundtrip_rate

    # ── 工具方法 ──────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"CostModel(market={self.market!r}, "
            f"one_way={self.one_way_rate*100:.2f}%, "
            f"roundtrip={self.roundtrip_rate*100:.2f}%)"
        )


# ── 常用預設實例 ──────────────────────────────────────────
TW_COST     = CostModel("TW")
US_COST     = CostModel("US")
CRYPTO_COST = CostModel("CRYPTO")


if __name__ == "__main__":
    for mkt in ("TW", "US", "CRYPTO"):
        cm = CostModel(mkt)
        price = 100.0
        print(f"\n[{mkt}] {cm}")
        print(f"  來回成本金額       : {cm.roundtrip_cost(price):.4f}")
        print(f"  真實成本價         : {cm.cost_basis(price):.4f}")
        print(f"  損益兩平最低出場價  : {cm.min_profit_exit(price):.4f}")
        print(f"  淨利潤（出 115）    : {cm.net_pnl_pct(price, 115.0):.2f}%")
        print(f"  7% 停損觸發門檻    : {cm.adjusted_stop_loss_pct(0.07)*100:.2f}% 跌幅")
        print(f"  15% 停利毛利門檻   : {cm.adjusted_take_profit_pct(0.15)*100:.2f}% 漲幅")
