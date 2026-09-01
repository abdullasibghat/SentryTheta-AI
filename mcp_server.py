import sys
import json
import logging
from typing import Dict, Any, List

# Load environment
from dotenv import load_dotenv
load_dotenv()

from backend.alpaca_helper import AlpacaHelper
from backend.risk_engine import RiskEngine
from backend.agent import SentryThetaAgent

# Configure basic logging to stderr so it doesn't corrupt stdout (which is used for JSON-RPC messages)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("SentryTheta.MCP")

# Initialize backends
alpaca = AlpacaHelper()
risk_engine = RiskEngine()
agent = SentryThetaAgent(alpaca, risk_engine)

def get_tools_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "get_portfolio_status",
            "description": "Fetch portfolio metrics (equity, cash, P&L) and current active options positions.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "analyze_and_propose_trade",
            "description": "Analyze sentiment for a target stock and search options chains to propose a risk-checked option trade strategy.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The stock ticker symbol (e.g. AAPL, MSFT, NVDA, SPY, QQQ)"
                    }
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "execute_option_order",
            "description": "Directly place an option contract trade order (buy/sell). Evaluates risk gates first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The OCC Option Symbol (e.g., AAPL260904C00220000)"
                    },
                    "qty": {
                        "type": "integer",
                        "description": "Quantity of contracts to trade (each contract represents 100 shares)"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["buy", "sell"],
                        "description": "Order side (buy to open/close or sell to open/close)"
                    },
                    "price": {
                        "type": "number",
                        "description": "Approximate current premium price per contract (for risk engine evaluation)"
                    }
                },
                "required": ["symbol", "qty", "side", "price"]
            }
        },
        {
            "name": "update_sentry_settings",
            "description": "Dynamically adjust options strategy risk engine thresholds.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "max_position_size_pct": {
                        "type": "number",
                        "description": "Maximum size of a single trade as percentage of equity"
                    },
                    "max_daily_drawdown_pct": {
                        "type": "number",
                        "description": "Maximum daily loss percentage threshold before trading is blocked"
                    },
                    "stop_loss_pct": {
                        "type": "number",
                        "description": "Percentage loss threshold to auto-liquidate active positions"
                    },
                    "take_profit_pct": {
                        "type": "number",
                        "description": "Percentage gain target to auto-harvest profits"
                    }
                }
            }
        }
    ]

def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"Handling tool call: {name} with args {arguments}")
    
    if name == "get_portfolio_status":
        acc = alpaca.get_account_info()
        positions = alpaca.get_active_positions()
        
        status_txt = (
            f"=== Portfolio Status (Mock Mode: {acc['is_mock']}) ===\n"
            f"Total Equity: ${acc['equity']:.2f}\n"
            f"Cash Balance: ${acc['cash']:.2f}\n"
            f"Buying Power: ${acc['buying_power']:.2f}\n"
            f"Today's P&L: ${acc['today_pl']:.2f} ({acc['today_plpc']*100:+.2f}%)\n\n"
            f"Active Options Contracts ({len(positions)}):\n"
        )
        
        if not positions:
            status_txt += "- No active options positions."
        for pos in positions:
            status_txt += (
                f"- {pos['symbol']}: {pos['side'].upper()} {pos['qty']}x {pos['type'].upper()} "
                f"Entry: ${pos['entry_price']:.2f} | Current: ${pos['current_price']:.2f} | "
                f"P&L: {pos['unrealized_pl']:+.2f} ({pos['unrealized_plpc']*100:+.1f}%)\n"
            )
            
        return {
            "content": [{"type": "text", "text": status_txt}]
        }
        
    elif name == "analyze_and_propose_trade":
        ticker = arguments.get("ticker", "").upper().strip()
        if not ticker:
            return {"content": [{"type": "text", "text": "Error: Ticker symbol is required."}]}
            
        sentiment, analysis = agent.analyze_market_sentiment(ticker)
        proposal = agent.propose_options_trade(ticker, sentiment)
        
        result_txt = (
            f"=== Market Analysis for {ticker} ===\n"
            f"Market Sentiment Score: {sentiment:+.2f}\n"
            f"LLM Sentiment Driver: {analysis}\n\n"
        )
        
        if proposal:
            result_txt += (
                f"=== Proposed Option Strategy ===\n"
                f"Strategy: {proposal['strategy']}\n"
                f"Contract Symbol: {proposal['symbol']}\n"
                f"Leg action: {proposal['side'].upper()} {proposal['qty']} contract(s)\n"
                f"Strike Price: ${proposal['strike']}\n"
                f"Expiration Date: {proposal['expiration']}\n"
                f"Est. Premium per Contract: ${proposal['premium']:.2f}\n"
                f"Total Capital Committed: ${proposal['total_value']:.2f}\n\n"
            )
            
            # Check Risk
            acc = alpaca.get_account_info()
            approved, risk_reason = risk_engine.evaluate_trade(
                symbol=proposal["symbol"],
                qty=proposal["qty"],
                premium_per_contract=proposal["premium"],
                side=proposal["side"],
                account_info=acc
            )
            
            result_txt += (
                f"=== Sentry Risk Assessment ===\n"
                f"Status: {'APPROVED' if approved else 'REJECTED'}\n"
                f"Assessment Detail: {risk_reason}\n"
            )
        else:
            result_txt += f"=== Proposed Option Strategy ===\nNo viable option strategy found in current chain for {ticker}."
            
        return {
            "content": [{"type": "text", "text": result_txt}]
        }
        
    elif name == "execute_option_order":
        symbol = arguments.get("symbol")
        qty = arguments.get("qty")
        side = arguments.get("side")
        price = arguments.get("price")
        
        # Check risk
        acc = alpaca.get_account_info()
        approved, risk_reason = risk_engine.evaluate_trade(
            symbol=symbol,
            qty=qty,
            premium_per_contract=price,
            side=side,
            account_info=acc
        )
        
        if not approved:
            return {
                "content": [{"type": "text", "text": f"Execution Blocked by Risk Sentry. Reason: {risk_reason}"}]
            }
            
        # Execute
        res = alpaca.execute_options_trade(
            symbol=symbol,
            qty=qty,
            side=side,
            strategy_name="MCP Manual Order"
        )
        
        if res["success"]:
            msg = (
                f"Order successfully transmitted and filled!\n"
                f"Order ID: {res['order_id']}\n"
                f"Contract: {res['symbol']}\n"
                f"Action: {res['side'].upper()} {res['qty']} contract(s) filled (Status: {res['status']})."
            )
        else:
            msg = f"Order execution failed on Alpaca: {res.get('error')}"
            
        return {
            "content": [{"type": "text", "text": msg}]
        }
        
    elif name == "update_sentry_settings":
        if "max_position_size_pct" in arguments:
            risk_engine.max_position_size_pct = float(arguments["max_position_size_pct"])
        if "max_daily_drawdown_pct" in arguments:
            risk_engine.max_daily_drawdown_pct = float(arguments["max_daily_drawdown_pct"])
        if "stop_loss_pct" in arguments:
            risk_engine.stop_loss_pct = float(arguments["stop_loss_pct"])
        if "take_profit_pct" in arguments:
            risk_engine.take_profit_pct = float(arguments["take_profit_pct"])
            
        msg = (
            f"Risk settings updated successfully:\n"
            f"- Max Pos Size: {risk_engine.max_position_size_pct}%\n"
            f"- Max Daily Drawdown: {risk_engine.max_daily_drawdown_pct}%\n"
            f"- Stop Loss: {risk_engine.stop_loss_pct}%\n"
            f"- Take Profit: {risk_engine.take_profit_pct}%"
        )
        return {
            "content": [{"type": "text", "text": msg}]
        }
        
    else:
        return {"content": [{"type": "text", "text": f"Error: Tool '{name}' not found."}]}

def main():
    logger.info("SentryTheta MCP Stdio Server started.")
    
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            # Ensure JSON-RPC protocol
            if "jsonrpc" not in request:
                continue
                
            req_id = request.get("id")
            method = request.get("method")
            
            # 1. Initialize
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "sentrytheta-mcp",
                            "version": "1.0.0"
                        }
                    }
                }
                
            # 2. List tools
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": get_tools_list()
                    }
                }
                
            # 3. Call tool
            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                
                result = handle_tool_call(tool_name, tool_args)
                
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found"
                    }
                }
                
            # Send response to stdout
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            
        except Exception as e:
            logger.error(f"Error handling JSON-RPC message: {e}")
            try:
                # Attempt to return general parse error
                sys.stdout.write(json.dumps({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32700,
                        "message": f"Parse error or execution failure: {str(e)}"
                    }
                }) + "\n")
                sys.stdout.flush()
            except:
                pass

if __name__ == "__main__":
    main()
