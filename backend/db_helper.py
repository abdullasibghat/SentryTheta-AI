import os
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("SentryTheta.DBHelper")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sentrytheta.db"))

class DBHelper:
    def __init__(self):
        self.db_path = DB_PATH
        self.init_db()

    def get_connection(self):
        """Returns a connection to the SQLite database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn

    def init_db(self):
        """Initialize SQLite database tables if they do not exist."""
        logger.info(f"Initializing database at: {self.db_path}")
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 1. Settings Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # 2. Terminal Logs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS terminal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                message TEXT
            )
        """)
        
        # 3. Mock Portfolio Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mock_portfolio (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash REAL,
                initial_equity REAL
            )
        """)
        
        # Initialize default mock portfolio if empty
        cursor.execute("SELECT COUNT(*) FROM mock_portfolio")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO mock_portfolio (id, cash, initial_equity) VALUES (1, 95000.0, 100000.0)"
            )
        
        # 4. Mock Positions Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mock_positions (
                symbol TEXT PRIMARY KEY,
                underlying_symbol TEXT,
                qty INTEGER,
                entry_price REAL,
                current_price REAL,
                side TEXT,
                type TEXT,
                strike REAL,
                expiration TEXT,
                market_value REAL,
                cost_basis REAL,
                unrealized_pl REAL,
                unrealized_plpc REAL
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("Database tables initialized successfully.")

    # --- Settings Handlers ---
    def get_setting(self, key: str, default: Any = None) -> Any:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default

    def set_setting(self, key: str, value: Any):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )
        conn.commit()
        conn.close()

    def get_all_settings(self) -> Dict[str, str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        conn.close()
        return {row["key"]: row["value"] for row in rows}

    # --- Logs Handlers ---
    def add_log(self, message: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO terminal_logs (timestamp, message) VALUES (?, ?)",
            (timestamp, message)
        )
        conn.commit()
        conn.close()

    def get_logs(self, limit: int = 100) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT message FROM terminal_logs ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        # Return in chronological order
        return [row["message"] for row in reversed(rows)]

    def clear_all_logs(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM terminal_logs")
        conn.commit()
        conn.close()

    # --- Mock Portfolio Handlers ---
    def get_mock_portfolio(self) -> Tuple[float, float]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT cash, initial_equity FROM mock_portfolio WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return float(row["cash"]), float(row["initial_equity"])
        return 95000.0, 100000.0

    def save_mock_portfolio(self, cash: float, initial_equity: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE mock_portfolio SET cash = ?, initial_equity = ? WHERE id = 1",
            (cash, initial_equity)
        )
        conn.commit()
        conn.close()

    # --- Mock Positions Handlers ---
    def get_mock_positions(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mock_positions")
        rows = cursor.fetchall()
        conn.close()
        
        positions = []
        for row in rows:
            positions.append({
                "symbol": row["symbol"],
                "underlying_symbol": row["underlying_symbol"],
                "qty": int(row["qty"]),
                "entry_price": float(row["entry_price"]),
                "current_price": float(row["current_price"]),
                "side": row["side"],
                "type": row["type"],
                "strike": float(row["strike"]),
                "expiration": row["expiration"],
                "market_value": float(row["market_value"]),
                "cost_basis": float(row["cost_basis"]),
                "unrealized_pl": float(row["unrealized_pl"]),
                "unrealized_plpc": float(row["unrealized_plpc"])
            })
        return positions

    def save_mock_position(self, symbol: str, pos: Dict[str, Any]):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO mock_positions (
                symbol, underlying_symbol, qty, entry_price, current_price,
                side, type, strike, expiration, market_value, cost_basis,
                unrealized_pl, unrealized_plpc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            pos["underlying_symbol"],
            int(pos["qty"]),
            float(pos["entry_price"]),
            float(pos["current_price"]),
            pos["side"],
            pos["type"],
            float(pos["strike"]),
            pos["expiration"],
            float(pos["market_value"]),
            float(pos["cost_basis"]),
            float(pos["unrealized_pl"]),
            float(pos["unrealized_plpc"])
        ))
        conn.commit()
        conn.close()

    def delete_mock_position(self, symbol: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mock_positions WHERE symbol = ?", (symbol,))
        conn.commit()
        conn.close()
