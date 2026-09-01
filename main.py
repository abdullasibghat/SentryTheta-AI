import os
import sys
import argparse
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

# Setup root logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SentryTheta.CLI")

def parse_args():
    parser = argparse.ArgumentParser(
        description="SentryTheta AI — CLI Command Launcher & Trading Agent Desk"
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")
    
    # 1. run-server
    subparsers.add_parser("run-server", help="Launch the FastAPI dashboard server")
    
    # 2. run-agent
    subparsers.add_parser("run-agent", help="Run the autonomous agent trading loop via CLI")
    
    # 3. test-trading
    test_parser = subparsers.add_parser("test-trading", help="Test connection and run dry-run mock scenario")
    test_parser.add_argument("--mock", action="store_true", help="Force mock testing mode")
    
    return parser.parse_args()

def run_server_command():
    logger.info("Initializing SentryTheta Server...")
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"Starting server on http://{host}:{port}")
    uvicorn.run("backend.server:app", host=host, port=port, reload=False)

async def run_agent_loop_async():
    """Runs a standalone agent scanning loop in the terminal (CLI mode)."""
    logger.info("Starting SentryTheta Agent in standalone CLI mode.")
    from backend.alpaca_helper import AlpacaHelper
    from backend.risk_engine import RiskEngine
    from backend.agent import SentryThetaAgent
    
    alpaca = AlpacaHelper()
    risk = RiskEngine()
    agent = SentryThetaAgent(alpaca, risk)
    
    tickers = [t.strip() for t in os.getenv("TARGET_TICKERS", "AAPL,MSFT,NVDA,SPY,QQQ").split(",")]
    scan_interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    trading_mode = os.getenv("TRADING_MODE", "autopilot").lower()
    
    logger.info(f"Stand-alone scanner running in {trading_mode.upper()} mode.")
    logger.info(f"Target tickers: {tickers} | Scan Interval: {scan_interval}s")
    
    try:
        while True:
            proposals, logs = agent.run_agent_scan(tickers)
            for log in logs:
                print(f"[{trading_mode.upper()}] {log}")
            
            if proposals and trading_mode == "autopilot":
                proposal = proposals[0]
                logger.info(f"Autopilot: Executing approved trade for {proposal['symbol']}")
                res = alpaca.execute_options_trade(
                    symbol=proposal["symbol"],
                    qty=proposal["qty"],
                    side=proposal["side"],
                    strategy_name=proposal["strategy"]
                )
                if res["success"]:
                    logger.info(f"Order Completed! ID: {res['order_id']}")
                else:
                    logger.error(f"Order failed: {res.get('error')}")
            elif proposals:
                proposal = proposals[0]
                logger.warning(
                    f"Copilot Mode: Proposed trade requires approval: {proposal['side'].upper()} "
                    f"{proposal['qty']}x {proposal['symbol']} at ${proposal['premium']:.2f}. "
                    f"Approval must be done via Web Dashboard."
                )
                
            await asyncio.sleep(scan_interval)
    except KeyboardInterrupt:
        logger.info("Standalone agent execution stopped by user.")

def run_agent_command():
    asyncio.run(run_agent_loop_async())

def run_test_command(force_mock: bool):
    logger.info("Starting connection testing and agent dry run...")
    from backend.alpaca_helper import AlpacaHelper
    from backend.risk_engine import RiskEngine
    from backend.agent import SentryThetaAgent
    
    if force_mock:
        os.environ["ALPACA_API_KEY"] = "your_alpaca_key_here"
        
    alpaca = AlpacaHelper()
    risk = RiskEngine()
    agent = SentryThetaAgent(alpaca, risk)
    
    logger.info("1. Testing Account Connection...")
    acc_info = alpaca.get_account_info()
    logger.info(f"Account Equity: ${acc_info['equity']:.2f} (Mock={acc_info['is_mock']})")
    
    logger.info("2. Testing Option Chain Lookup...")
    chain = alpaca.get_option_chain("AAPL")
    if chain:
        logger.info(f"Successfully retrieved {len(chain)} option contracts. First: {chain[0]['symbol']} strike {chain[0]['strike']} last price {chain[0]['last_price']}")
    else:
        logger.error("Failed to retrieve option chain.")
        
    logger.info("3. Testing Risk Engine Trade Approval...")
    approved, reason = risk.evaluate_trade(
        symbol="AAPL260904C00220000",
        qty=2,
        premium_per_contract=3.50,
        side="buy",
        account_info=acc_info
    )
    logger.info(f"Risk Check Result: Approved={approved} | Reason: {reason}")
    
    logger.info("4. Testing Option Order Placement...")
    res = alpaca.execute_options_trade(
        symbol="AAPL260904C00220000",
        qty=1,
        side="buy",
        strategy_name="Dry Run Test"
    )
    if res["success"]:
        logger.info(f"Order Executed Successfully! Order ID: {res['order_id']}")
    else:
        logger.error(f"Order execution failed: {res.get('error')}")
        
    logger.info("Dry run testing completed.")

def main():
    args = parse_args()
    
    if args.command == "run-server":
        run_server_command()
    elif args.command == "run-agent":
        run_agent_command()
    elif args.command == "test-trading":
        run_test_command(args.mock)

if __name__ == "__main__":
    main()
