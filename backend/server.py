import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.alpaca_helper import AlpacaHelper
from backend.risk_engine import RiskEngine
from backend.agent import SentryThetaAgent

load_dotenv()

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SentryTheta.Server")

# FastAPI App Setup
app = FastAPI()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
alpaca = AlpacaHelper()
risk_engine = RiskEngine()
agent = SentryThetaAgent(alpaca, risk_engine)

# Active WebSockets connection pool
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                # Connection might be dead
                pass

manager = ConnectionManager()

db = alpaca.db

# Load settings from DB with fallback to env/defaults
db_settings = db.get_all_settings()

trading_mode = db_settings.get("trading_mode", os.getenv("TRADING_MODE", "copilot")).lower()
scan_interval = int(db_settings.get("scan_interval", os.getenv("SCAN_INTERVAL_SECONDS", "60")))

tickers_str = db_settings.get("tickers", os.getenv("TARGET_TICKERS", "AAPL,MSFT,NVDA,SPY,QQQ"))
tickers = [t.strip() for t in tickers_str.split(",")]

# Load risk parameters into RiskEngine
risk_engine.max_position_size_pct = float(db_settings.get("max_position_size_pct", os.getenv("MAX_POSITION_SIZE_PERCENT", "5.0")))
risk_engine.max_daily_drawdown_pct = float(db_settings.get("max_daily_drawdown_pct", os.getenv("MAX_DAILY_DRAWDOWN_PERCENT", "3.0")))
risk_engine.stop_loss_pct = float(db_settings.get("stop_loss_pct", os.getenv("STOP_LOSS_PERCENT", "15.0")))
risk_engine.take_profit_pct = float(db_settings.get("take_profit_pct", os.getenv("TAKE_PROFIT_PERCENT", "30.0")))

# Load historical logs from DB
terminal_logs = db.get_logs(100)
if not terminal_logs:
    terminal_logs = ["SentryTheta Server initialized. Waiting for scanner cycle..."]
    db.add_log(terminal_logs[0])

# Global State
state = {
    "trading_mode": trading_mode,
    "scan_interval": scan_interval,
    "tickers": tickers,
    "pending_proposal": None,
    "terminal_logs": terminal_logs,
    "optionable_assets": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"] # default fallback
}

# Settings Schema
class SettingsRequest(BaseModel):
    trading_mode: str
    scan_interval: int
    tickers: List[str]
    max_position_size_pct: float
    max_daily_drawdown_pct: float
    stop_loss_pct: float
    take_profit_pct: float

# Append terminal log and broadcast
async def log_and_broadcast(message: str):
    logger.info(message)
    state["terminal_logs"].append(message)
    if len(state["terminal_logs"]) > 100:
        state["terminal_logs"].pop(0)
    db.add_log(message)  # Persist log to SQLite
    await manager.broadcast({"type": "log", "data": message})

# REST API Endpoints
@app.get("/api/status")
async def get_status():
    acc_info = alpaca.get_account_info()
    positions = alpaca.get_active_positions()
    return {
        "account": acc_info,
        "positions": positions,
        "settings": {
            "trading_mode": state["trading_mode"],
            "scan_interval": state["scan_interval"],
            "tickers": state["tickers"],
            "max_position_size_pct": risk_engine.max_position_size_pct,
            "max_daily_drawdown_pct": risk_engine.max_daily_drawdown_pct,
            "stop_loss_pct": risk_engine.stop_loss_pct,
            "take_profit_pct": risk_engine.take_profit_pct,
        },
        "pending_proposal": state["pending_proposal"],
        "logs": state["terminal_logs"]
    }

@app.get("/api/assets")
async def get_assets_endpoint():
    return state.get("optionable_assets", ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"])

@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    if req.trading_mode not in ["copilot", "autopilot"]:
        raise HTTPException(status_code=400, detail="Invalid trading mode.")
        
    state["trading_mode"] = req.trading_mode
    state["scan_interval"] = max(10, req.scan_interval) # minimum 10 seconds
    state["tickers"] = [t.upper().strip() for t in req.tickers]
    
    risk_engine.max_position_size_pct = req.max_position_size_pct
    risk_engine.max_daily_drawdown_pct = req.max_daily_drawdown_pct
    risk_engine.stop_loss_pct = req.stop_loss_pct
    risk_engine.take_profit_pct = req.take_profit_pct
    
    # Save settings to SQLite
    db.set_setting("trading_mode", state["trading_mode"])
    db.set_setting("scan_interval", state["scan_interval"])
    db.set_setting("tickers", ",".join(state["tickers"]))
    db.set_setting("max_position_size_pct", risk_engine.max_position_size_pct)
    db.set_setting("max_daily_drawdown_pct", risk_engine.max_daily_drawdown_pct)
    db.set_setting("stop_loss_pct", risk_engine.stop_loss_pct)
    db.set_setting("take_profit_pct", risk_engine.take_profit_pct)
    
    await log_and_broadcast(
        f"⚙️ System settings updated. Mode={state['trading_mode'].upper()}, "
        f"Tickers={state['tickers']}"
    )
    
    # Broadcast updated status to all clients
    await broadcast_state()
    return {"status": "success"}

@app.post("/api/copilot/approve")
async def approve_trade():
    proposal = state["pending_proposal"]
    if not proposal:
        raise HTTPException(status_code=400, detail="No pending proposal to approve.")
        
    await log_and_broadcast(f"👍 User APPROVED proposal for {proposal['symbol']}")
    
    # Execute order
    res = alpaca.execute_options_trade(
        symbol=proposal["symbol"],
        qty=proposal["qty"],
        side=proposal["side"],
        strategy_name=proposal["strategy"]
    )
    
    if res["success"]:
        await log_and_broadcast(
            f"✅ [Executor] Order filled: {res['side'].upper()} {res['qty']}x {res['symbol']} "
            f"at ${res.get('price', proposal['premium']):.2f}. Order ID: {res['order_id']}"
        )
        state["pending_proposal"] = None
        await broadcast_state()
        return {"status": "success", "detail": res}
    else:
        await log_and_broadcast(f"❌ [Executor] Order failed: {res.get('error')}")
        state["pending_proposal"] = None
        await broadcast_state()
        raise HTTPException(status_code=500, detail=res.get("error"))

@app.post("/api/copilot/reject")
async def reject_trade():
    proposal = state["pending_proposal"]
    if not proposal:
        raise HTTPException(status_code=400, detail="No pending proposal to reject.")
        
    await log_and_broadcast(f"👎 User REJECTED proposal for {proposal['symbol']}. Clearing proposal.")
    state["pending_proposal"] = None
    await broadcast_state()
    return {"status": "success"}

# WebSocket Handler
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial status
        acc_info = alpaca.get_account_info()
        positions = alpaca.get_active_positions()
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "account": acc_info,
                "positions": positions,
                "settings": {
                    "trading_mode": state["trading_mode"],
                    "scan_interval": state["scan_interval"],
                    "tickers": state["tickers"],
                    "max_position_size_pct": risk_engine.max_position_size_pct,
                    "max_daily_drawdown_pct": risk_engine.max_daily_drawdown_pct,
                    "stop_loss_pct": risk_engine.stop_loss_pct,
                    "take_profit_pct": risk_engine.take_profit_pct,
                },
                "pending_proposal": state["pending_proposal"],
                "logs": state["terminal_logs"]
            }
        }))
        
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def broadcast_state():
    """Broadcast current portfolio state, positions and settings to all websockets."""
    try:
        acc_info = alpaca.get_account_info()
        positions = alpaca.get_active_positions()
        await manager.broadcast({
            "type": "status_update",
            "data": {
                "account": acc_info,
                "positions": positions,
                "pending_proposal": state["pending_proposal"]
            }
        })
    except Exception as e:
        logger.error(f"Error broadcasting state: {e}")

# Background Scanner Loop
async def scan_market_loop():
    logger.info("Starting agent scanner background loop...")
    while True:
        try:
            # Run scan cycle
            proposals, logs = agent.run_agent_scan(state["tickers"])
            
            # Send logs to UI
            for log in logs:
                await log_and_broadcast(log)
                await asyncio.sleep(0.1) # brief pause to simulate real-time printing
                
            if proposals:
                proposal = proposals[0] # Handle first approved proposal
                
                if state["trading_mode"] == "autopilot":
                    # Autonomous execution
                    await log_and_broadcast(f"🤖 [Executor] Autopilot mode enabled. Executing proposal autonomously...")
                    res = alpaca.execute_options_trade(
                        symbol=proposal["symbol"],
                        qty=proposal["qty"],
                        side=proposal["side"],
                        strategy_name=proposal["strategy"]
                    )
                    if res["success"]:
                        await log_and_broadcast(
                            f"✅ [Executor] Order filled: {res['side'].upper()} {res['qty']}x {res['symbol']} "
                            f"at ${res.get('price', proposal['premium']):.2f}. Order ID: {res['order_id']}"
                        )
                    else:
                        await log_and_broadcast(f"❌ [Executor] Autopilot order execution failed: {res.get('error')}")
                else:
                    # Copilot mode (Queue for approval)
                    await log_and_broadcast(f"🔔 [Strategist] Proposed trade added to Copilot Queue. Awaiting approval...")
                    state["pending_proposal"] = proposal
                    # Broadcast the trade proposal to trigger UI alerts
                    await manager.broadcast({
                        "type": "proposal",
                        "data": proposal
                    })
            
            # Periodic P&L/Status updates between scans
            await broadcast_state()
            
        except Exception as e:
            logger.error(f"Error in background scanner cycle: {e}")
            
        # Sleep for specified interval
        await asyncio.sleep(state["scan_interval"])

async def cache_optionable_assets_task():
    logger.info("Background caching of optionable assets started...")
    if alpaca.is_mock:
        # Default mock popular optionable tickers
        state["optionable_assets"] = [
            "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL", "NFLX", 
            "SPY", "QQQ", "IWM", "DIS", "COIN", "PLTR", "JPM", "WMT", "V", "MA", "UNH"
        ]
        logger.info(f"Loaded {len(state['optionable_assets'])} mock optionable tickers.")
        return
        
    try:
        # Run synchronous SDK call in executor to avoid blocking the asyncio event loop!
        loop = asyncio.get_event_loop()
        assets = await loop.run_in_executor(None, alpaca.trading_client.get_all_assets)
        
        opt_symbols = [
            a.symbol for a in assets 
            if a.tradable and a.attributes and "has_options" in a.attributes
        ]
        
        if opt_symbols:
            state["optionable_assets"] = sorted(opt_symbols)
            logger.info(f"Successfully cached {len(opt_symbols)} optionable assets from Alpaca.")
        else:
            logger.warning("Alpaca returned no optionable assets. Using defaults.")
    except Exception as e:
        logger.error(f"Failed to cache Alpaca optionable assets: {e}. Using defaults.")

# Start background loop on startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cache_optionable_assets_task())
    asyncio.create_task(scan_market_loop())

# Serve static frontend files
# Front-end folder must contain index.html, style.css, app.js
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

if os.path.exists(frontend_dir):
    logger.info(f"Serving static frontend files from: {frontend_dir}")
    # Route for fallback/index.html
    @app.get("/")
    async def read_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
        
    app.mount("/", StaticFiles(directory=frontend_dir), name="static")
else:
    logger.error(f"Frontend directory '{frontend_dir}' not found! Backend only mode.")
