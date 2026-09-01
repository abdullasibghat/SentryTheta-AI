import os
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger("SentryTheta.RiskEngine")

class RiskEngine:
    def __init__(self):
        # Risk settings from env or defaults
        self.max_position_size_pct = float(os.getenv("MAX_POSITION_SIZE_PERCENT", "5.0"))
        self.max_daily_drawdown_pct = float(os.getenv("MAX_DAILY_DRAWDOWN_PERCENT", "3.0"))
        self.stop_loss_pct = float(os.getenv("STOP_LOSS_PERCENT", "15.0"))
        self.take_profit_pct = float(os.getenv("TAKE_PROFIT_PERCENT", "30.0"))
        
        logger.info(
            f"Risk Engine initialized: MaxPos={self.max_position_size_pct}%, "
            f"MaxDrawdown={self.max_daily_drawdown_pct}%, "
            f"SL={self.stop_loss_pct}%, TP={self.take_profit_pct}%"
        )

    def evaluate_trade(
        self, 
        symbol: str, 
        qty: int, 
        premium_per_contract: float, 
        side: str, 
        account_info: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Evaluate if a proposed trade satisfies risk parameters.
        Returns:
            (is_approved: bool, reason: str)
        """
        equity = account_info.get("equity", 100000.0)
        cash = account_info.get("cash", 100000.0)
        today_pl = account_info.get("today_pl", 0.0)
        
        # Calculate cost/credit of trade
        # Option contract represents 100 shares
        trade_value = premium_per_contract * qty * 100
        
        # 1. Daily Drawdown Check
        # Reject new trades if today's drawdown exceeds limit
        drawdown_limit = equity * (self.max_daily_drawdown_pct / 100.0)
        if today_pl < 0 and abs(today_pl) >= drawdown_limit:
            reason = f"Daily drawdown limit of {self.max_daily_drawdown_pct}% exceeded (Current today's P&L: ${today_pl:.2f}). Trading blocked."
            logger.warning(reason)
            return False, reason
            
        # 2. Position Size Limit Check
        # A single position should not exceed MAX_POSITION_SIZE_PERCENT of total equity
        max_position_size = equity * (self.max_position_size_pct / 100.0)
        
        if side.lower() == "buy":
            # For buying options, the risk is the premium paid
            if trade_value > max_position_size:
                reason = (
                    f"Position size exceeds limit. Proposed cost: ${trade_value:.2f}, "
                    f"Max allowed ({self.max_position_size_pct}% of equity): ${max_position_size:.2f}."
                )
                logger.warning(reason)
                return False, reason
                
            # Cash availability check
            if trade_value > cash:
                reason = f"Insufficient cash to execute trade. Cost: ${trade_value:.2f}, Cash: ${cash:.2f}."
                logger.warning(reason)
                return False, reason
                
        else: # Selling option (premium collection / write)
            # In short options, margin requirement or collateral must be evaluated.
            # For simplicity, we limit short premium trades to the same position size
            # based on collateral value or margin impact.
            if trade_value > max_position_size:
                reason = (
                    f"Premium size exceeds limit. Proposed margin value: ${trade_value:.2f}, "
                    f"Max allowed ({self.max_position_size_pct}% of equity): ${max_position_size:.2f}."
                )
                logger.warning(reason)
                return False, reason
                
        return True, "Trade satisfies all Sentry Risk limits."

    def check_portfolio_risk(self, active_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Scan active positions and return positions that breach Stop Loss or Take Profit targets.
        Returns a list of trade suggestions to close positions.
        """
        exit_signals = []
        
        for pos in active_positions:
            unrealized_plpc = pos.get("unrealized_plpc", 0.0) * 100 # convert to %
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            
            # Stop Loss (SL) check (Negative P&L)
            if unrealized_plpc <= -self.stop_loss_pct:
                logger.warning(f"Stop Loss breached for {symbol}: {unrealized_plpc:.2f}% (Limit: -{self.stop_loss_pct}%)")
                exit_signals.append({
                    "symbol": symbol,
                    "qty": abs(qty),
                    "side": "sell" if qty > 0 else "buy",
                    "reason": f"Stop Loss target (-{self.stop_loss_pct}%) hit at {unrealized_plpc:.2f}%."
                })
                
            # Take Profit (TP) check (Positive P&L)
            elif unrealized_plpc >= self.take_profit_pct:
                logger.info(f"Take Profit hit for {symbol}: {unrealized_plpc:.2f}% (Limit: +{self.take_profit_pct}%)")
                exit_signals.append({
                    "symbol": symbol,
                    "qty": abs(qty),
                    "side": "sell" if qty > 0 else "buy",
                    "reason": f"Take Profit target (+{self.take_profit_pct}%) hit at {unrealized_plpc:.2f}%."
                })
                
        return exit_signals
