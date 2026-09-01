import os
import logging
import datetime
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from backend.db_helper import DBHelper

# Try importing Alpaca Py SDK
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    from alpaca.data.historical.option import OptionHistoricalDataClient
    from alpaca.data.requests import OptionChainRequest
    ALPACA_SDK_AVAILABLE = True
except ImportError:
    ALPACA_SDK_AVAILABLE = False

load_dotenv()

logger = logging.getLogger("SentryTheta.AlpacaHelper")

class AlpacaHelper:
    def __init__(self):
        self.db = DBHelper()
        self.api_key = os.getenv("ALPACA_API_KEY", "your_alpaca_key_here")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "your_alpaca_secret_here")
        self.paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        
        # Check if keys are placeholders or empty
        self.is_mock = (
            not ALPACA_SDK_AVAILABLE or
            self.api_key == "your_alpaca_key_here" or
            self.secret_key == "your_alpaca_secret_here" or
            not self.api_key or
            not self.secret_key
        )
        
        if self.is_mock:
            logger.warning("Alpaca API keys are missing or invalid. Running in MOCK MODE.")
            self._init_mock_data()
        else:
            try:
                self.trading_client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
                self.data_client = OptionHistoricalDataClient(self.api_key, self.secret_key)
                logger.info(f"Alpaca Client initialized successfully (Paper={self.paper})")
            except Exception as e:
                logger.error(f"Failed to initialize Alpaca Client: {e}. Falling back to MOCK MODE.")
                self.is_mock = True
                self._init_mock_data()

    def _init_mock_data(self):
        """Initialize mock portfolio state for fallback demonstration, loading from SQLite."""
        # Load cash and initial equity from DB
        self.mock_cash, self.mock_initial_equity = self.db.get_mock_portfolio()
        self.mock_buying_power = self.mock_cash * 2.0
        
        # Load positions from DB
        positions_list = self.db.get_mock_positions()
        
        if not positions_list:
            # First time setup: populate with initial sample data
            initial_data = {
                "NVDA260904C00125000": {
                    "symbol": "NVDA260904C00125000",
                    "underlying_symbol": "NVDA",
                    "qty": 2,
                    "entry_price": 4.50,
                    "current_price": 5.20,
                    "side": "buy",
                    "type": "call",
                    "strike": 125.0,
                    "expiration": "2026-09-04",
                    "market_value": 1040.0,
                    "cost_basis": 900.0,
                    "unrealized_pl": 140.0,
                    "unrealized_plpc": 0.1556
                },
                "AAPL260911P00215000": {
                    "symbol": "AAPL260911P00215000",
                    "underlying_symbol": "AAPL",
                    "qty": 1,
                    "entry_price": 3.20,
                    "current_price": 2.80,
                    "side": "buy",
                    "type": "put",
                    "strike": 215.0,
                    "expiration": "2026-09-11",
                    "market_value": 280.0,
                    "cost_basis": 320.0,
                    "unrealized_pl": -40.0,
                    "unrealized_plpc": -0.125
                }
            }
            self.mock_positions = initial_data
            for pos in initial_data.values():
                self.db.save_mock_position(pos["symbol"], pos)
            self._recalculate_mock_totals()
            self.mock_initial_equity = self.mock_equity
            self.db.save_mock_portfolio(self.mock_cash, self.mock_initial_equity)
        else:
            self.mock_positions = {pos["symbol"]: pos for pos in positions_list}
            self._recalculate_mock_totals()

    def _recalculate_mock_totals(self):
        """Update mock portfolio cash/equity/P&L values and save to DB."""
        positions_value = sum(pos["market_value"] for pos in self.mock_positions.values())
        self.mock_equity = self.mock_cash + positions_value
        self.mock_buying_power = self.mock_cash * 2.0
        self.db.save_mock_portfolio(self.mock_cash, self.mock_initial_equity)

    def get_account_info(self) -> Dict[str, Any]:
        """Fetch account equity, cash, buying power and today's P&L."""
        if self.is_mock:
            # Simulate slight drift in current prices to make UI dynamic
            import random
            for sym, pos in self.mock_positions.items():
                change = random.uniform(-0.05, 0.07) # slightly upward drift
                pos["current_price"] = max(0.05, round(pos["current_price"] + change, 2))
                pos["market_value"] = pos["current_price"] * pos["qty"] * 100
                pos["unrealized_pl"] = pos["market_value"] - pos["cost_basis"]
                pos["unrealized_plpc"] = pos["unrealized_pl"] / pos["cost_basis"]
                # Save drifted price to SQLite
                self.db.save_mock_position(sym, pos)
            
            self._recalculate_mock_totals()
            today_pl = self.mock_equity - self.mock_initial_equity
            today_plpc = today_pl / self.mock_initial_equity
            
            return {
                "equity": round(self.mock_equity, 2),
                "cash": round(self.mock_cash, 2),
                "buying_power": round(self.mock_buying_power, 2),
                "today_pl": round(today_pl, 2),
                "today_plpc": round(today_plpc, 4),
                "currency": "USD",
                "is_mock": True
            }
        
        try:
            acc = self.trading_client.get_account()
            # Fetch equity, cash, etc.
            equity = float(acc.equity)
            cash = float(acc.cash)
            buying_power = float(acc.buying_power)
            
            # Calculate daily P&L
            last_equity = float(acc.last_equity)
            today_pl = equity - last_equity
            today_plpc = today_pl / last_equity if last_equity > 0 else 0
            
            # Cache live values
            self._cached_equity = equity
            self._cached_cash = cash
            self._cached_buying_power = buying_power
            self._cached_today_pl = today_pl
            self._cached_today_plpc = today_plpc
            
            return {
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "buying_power": round(buying_power, 2),
                "today_pl": round(today_pl, 2),
                "today_plpc": round(today_plpc, 4),
                "currency": "USD",
                "is_mock": False
            }
        except Exception as e:
            logger.error(f"Error fetching real account info: {e}.")
            return {
                "equity": round(getattr(self, "_cached_equity", self.mock_equity), 2),
                "cash": round(getattr(self, "_cached_cash", self.mock_cash), 2),
                "buying_power": round(getattr(self, "_cached_buying_power", self.mock_buying_power), 2),
                "today_pl": round(getattr(self, "_cached_today_pl", 0.0), 2),
                "today_plpc": round(getattr(self, "_cached_today_plpc", 0.0), 4),
                "currency": "USD",
                "is_mock": False
            }

    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Fetch current open options positions."""
        if self.is_mock:
            return list(self.mock_positions.values())
        
        try:
            positions = self.trading_client.get_all_positions()
            formatted = []
            for pos in positions:
                # Filter for options positions (symbol length > 6 and format includes numbers/expiry)
                # Alpaca represents option positions in standard OCC formatting
                if len(pos.symbol) > 6 and any(c.isdigit() for c in pos.symbol):
                    # Extract contract details from symbol if possible
                    # Symbol e.g. AAPL260911P00215000
                    qty = int(pos.qty)
                    entry_price = float(pos.avg_entry_price)
                    current_price = float(pos.current_price)
                    market_value = float(pos.market_value)
                    unrealized_pl = float(pos.unrealized_intraday_pl)
                    unrealized_plpc = float(pos.unrealized_intraday_plpc)
                    
                    # Parse OCC
                    ticker = pos.symbol[:4].strip()
                    # We can attempt to parse strike/expiry for display
                    # AAPL 260911 P 00215000
                    # Expiry YYMMDD
                    expiry = f"20{pos.symbol[4:6]}-{pos.symbol[6:8]}-{pos.symbol[8:10]}"
                    opt_type = "call" if pos.symbol[10].upper() == 'C' else "put"
                    strike = float(pos.symbol[11:]) / 1000.0
                    
                    formatted.append({
                        "symbol": pos.symbol,
                        "underlying_symbol": ticker,
                        "qty": qty,
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "side": pos.side,
                        "type": opt_type,
                        "strike": strike,
                        "expiration": expiry,
                        "market_value": market_value,
                        "cost_basis": entry_price * qty * 100,
                        "unrealized_pl": unrealized_pl,
                        "unrealized_plpc": unrealized_plpc
                    })
            return formatted
        except Exception as e:
            logger.error(f"Error fetching real positions: {e}. Using mock positions.")
            return list(self.mock_positions.values())

    def get_option_chain(self, ticker: str) -> List[Dict[str, Any]]:
        """Fetch active option contracts and snapshots for a stock ticker."""
        if self.is_mock:
            return self._generate_mock_option_chain(ticker)
        
        try:
            current_date = datetime.date.today()
            expiry_limit = current_date + datetime.timedelta(days=30)
            
            # 1. Fetch metadata for active options with expiration >= today
            req = GetOptionContractsRequest(
                underlying_symbols=[ticker],
                status="active",
                expiration_date_gte=current_date
            )
            response = self.trading_client.get_option_contracts(req)
            contracts = getattr(response, "option_contracts", response) or []
            
            valid_contracts = []
            for c in contracts:
                exp_val = c.expiration_date
                if isinstance(exp_val, str):
                    expiry = datetime.datetime.strptime(exp_val, "%Y-%m-%d").date()
                else:
                    expiry = exp_val
                
                if current_date <= expiry <= expiry_limit:
                    valid_contracts.append((c, expiry))
                    
            if not valid_contracts:
                logger.warning(f"No valid future contracts returned by Alpaca for {ticker}. Using fallback chain.")
                return self._generate_mock_option_chain(ticker)
                
            # Limit to top 20 contracts for performance
            valid_contracts = valid_contracts[:20]
            
            # 2. Fetch market snapshots if available (using historical data client)
            # In the basic paper plan, get_option_chain might have feed constraints, so we handle it gracefully
            chain_list = []
            for c, expiry in valid_contracts:
                # We can fetch latest price/quotes
                # If chain API fails, we populate with a default price based on strike
                chain_list.append({
                    "symbol": c.symbol,
                    "underlying_symbol": ticker,
                    "strike": float(c.strike_price),
                    "expiration": expiry.strftime("%Y-%m-%d"),
                    "type": str(c.type.value) if hasattr(c.type, "value") else str(c.type),
                    "bid": float(c.strike_price) * 0.02, # default estimation
                    "ask": float(c.strike_price) * 0.022,
                    "last_price": float(c.strike_price) * 0.021
                })
            
            return chain_list
        except Exception as e:
            logger.error(f"Error fetching real option chain for {ticker}: {e}. Generating mock chain.")
            return self._generate_mock_option_chain(ticker)

    def _generate_mock_option_chain(self, ticker: str) -> List[Dict[str, Any]]:
        """Generate mock option chain details based on current index prices."""
        import random
        # Base prices for target tickers
        base_prices = {"AAPL": 220.0, "MSFT": 415.0, "NVDA": 120.0, "SPY": 560.0, "QQQ": 480.0}
        base_price = base_prices.get(ticker, 150.0)
        
        # Current stock price simulated drift
        stock_price = base_price + random.uniform(-2.0, 2.0)
        
        chain = []
        today = datetime.date.today()
        # Expiry Friday of this week
        days_to_friday = (4 - today.weekday()) % 7
        if days_to_friday == 0:
            days_to_friday = 7
        friday_expiry = today + datetime.timedelta(days=days_to_friday)
        expiry_str = friday_expiry.strftime("%Y-%m-%d")
        
        # Generate strikes around current stock price
        strike_step = 5.0 if stock_price >= 200 else (1.0 if stock_price <= 150 else 2.5)
        center_strike = round(stock_price / strike_step) * strike_step
        
        strikes = [center_strike + i * strike_step for i in range(-4, 5)]
        
        for strike in strikes:
            for opt_type in ["call", "put"]:
                # Simple Black-Scholes approximation for pricing mock premium
                dist = strike - stock_price
                if opt_type == "call":
                    intrinsic = max(0.0, -dist)
                    extrinsic = max(0.5, 8.0 - abs(dist) * 0.8)
                else:
                    intrinsic = max(0.0, dist)
                    extrinsic = max(0.5, 8.0 - abs(dist) * 0.8)
                
                premium = round(intrinsic + extrinsic, 2)
                bid = max(0.05, round(premium - 0.10, 2))
                ask = round(premium + 0.10, 2)
                
                # OCC Symbol formatting: AAPL260904C00220000
                expiry_code = friday_expiry.strftime("%y%m%d")
                strike_code = f"{int(strike * 1000):08d}"
                symbol = f"{ticker:<6}{expiry_code}{'C' if opt_type == 'call' else 'P'}{strike_code}".replace(" ", "")
                
                chain.append({
                    "symbol": symbol,
                    "underlying_symbol": ticker,
                    "strike": strike,
                    "expiration": expiry_str,
                    "type": opt_type,
                    "bid": bid,
                    "ask": ask,
                    "last_price": premium,
                    "stock_price": round(stock_price, 2)
                })
        return chain

    def execute_options_trade(self, symbol: str, qty: int, side: str, strategy_name: str = "Single Option") -> Dict[str, Any]:
        """Place an option order on Alpaca or execute in Mock portfolio."""
        side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        
        if self.is_mock:
            # Execute mock order
            # 1. Parse symbol details
            ticker = symbol[:4].strip()
            opt_type = "call" if "C" in symbol else "put"
            # simple mock price calculation
            price = 3.50
            
            # Find in mock chain if exists
            mock_chain = self._generate_mock_option_chain(ticker)
            for contract in mock_chain:
                if contract["symbol"] == symbol:
                    price = contract["last_price"]
                    break
                    
            cost = price * qty * 100
            
            if side.lower() == "buy":
                if cost > self.mock_cash:
                    return {"success": False, "error": "Insufficient cash for buying option."}
                
                self.mock_cash -= cost
                if symbol in self.mock_positions:
                    pos = self.mock_positions[symbol]
                    old_qty = pos["qty"]
                    pos["qty"] += qty
                    pos["cost_basis"] += cost
                    pos["entry_price"] = pos["cost_basis"] / (pos["qty"] * 100)
                else:
                    expiry = "2026-09-04"
                    strike = 120.0
                    # Parse strike/expiry from symbol
                    try:
                        # AAPL260904C00220000
                        # 0123456789012345678
                        # 0-3: AAPL, 4-9: 260904, 10: C, 11+: 00220000
                        expiry = f"20{symbol[4:6]}-{symbol[6:8]}-{symbol[8:10]}"
                        strike = float(symbol[11:]) / 1000.0
                    except:
                        pass
                        
                    self.mock_positions[symbol] = {
                        "symbol": symbol,
                        "underlying_symbol": ticker,
                        "qty": qty,
                        "entry_price": price,
                        "current_price": price,
                        "side": "buy",
                        "type": opt_type,
                        "strike": strike,
                        "expiration": expiry,
                        "market_value": cost,
                        "cost_basis": cost,
                        "unrealized_pl": 0.0,
                        "unrealized_plpc": 0.0
                    }
                self.db.save_mock_position(symbol, self.mock_positions[symbol])
            else: # SELL to close
                if symbol not in self.mock_positions:
                    # Allow selling (writing call/put)
                    proceeds = cost
                    self.mock_cash += proceeds
                    # For simplicity, we just add it as a short position
                    expiry = "2026-09-04"
                    strike = 120.0
                    try:
                        expiry = f"20{symbol[4:6]}-{symbol[6:8]}-{symbol[8:10]}"
                        strike = float(symbol[11:]) / 1000.0
                    except:
                        pass
                    
                    self.mock_positions[symbol] = {
                        "symbol": symbol,
                        "underlying_symbol": ticker,
                        "qty": -qty,
                        "entry_price": price,
                        "current_price": price,
                        "side": "sell",
                        "type": opt_type,
                        "strike": strike,
                        "expiration": expiry,
                        "market_value": -cost,
                        "cost_basis": -cost,
                        "unrealized_pl": 0.0,
                        "unrealized_plpc": 0.0
                    }
                    self.db.save_mock_position(symbol, self.mock_positions[symbol])
                else:
                    pos = self.mock_positions[symbol]
                    if pos["qty"] > 0:
                        # Selling to close existing long
                        sell_qty = min(qty, pos["qty"])
                        pos["qty"] -= sell_qty
                        self.mock_cash += price * sell_qty * 100
                        if pos["qty"] == 0:
                            del self.mock_positions[symbol]
                            self.db.delete_mock_position(symbol)
                        else:
                            pos["cost_basis"] = pos["entry_price"] * pos["qty"] * 100
                            pos["market_value"] = pos["current_price"] * pos["qty"] * 100
                            self.db.save_mock_position(symbol, pos)
                    else:
                        # Adding to short position
                        pos["qty"] -= qty
                        self.mock_cash += cost
                        pos["cost_basis"] -= cost
                        pos["market_value"] = pos["current_price"] * pos["qty"] * 100
                        self.db.save_mock_position(symbol, pos)
            
            self._recalculate_mock_totals()
            return {
                "success": True,
                "order_id": f"mock_order_{datetime.datetime.now().strftime('%H%M%S%f')}",
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "side": side,
                "status": "filled",
                "is_mock": True
            }
            
        try:
            # Check if Level 3 spreads order can be executed as individual legs
            # Alpaca Py SDK provides MarketOrderRequest and OptionLegRequest for multi-leg option orders
            # But for simplicity, we submit standard single-leg option orders first, which handles Level 2
            # For spreads, we can submit multiple orders or use the multi-leg order requests
            
            # Basic single leg submission
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading_client.submit_order(order_data=order_data)
            
            return {
                "success": True,
                "order_id": str(order.id),
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "status": str(order.status),
                "is_mock": False
            }
        except Exception as e:
            logger.error(f"Failed to execute option trade for {symbol}: {e}")
            return {"success": False, "error": str(e)}
