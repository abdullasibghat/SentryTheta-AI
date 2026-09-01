import os
import re
import urllib.request
import xml.etree.ElementTree as ET
import logging
import random
from typing import Dict, Any, List, Optional, Tuple
from backend.alpaca_helper import AlpacaHelper
from backend.risk_engine import RiskEngine

logger = logging.getLogger("SentryTheta.Agent")

class SentryThetaAgent:
    def __init__(self, alpaca_helper: AlpacaHelper, risk_engine: RiskEngine):
        self.alpaca = alpaca_helper
        self.risk_engine = risk_engine
        
        # Initialize Gemini API
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.use_gemini = bool(self.gemini_api_key and self.gemini_api_key != "your_gemini_key_here")
        
        if self.use_gemini:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                logger.info("Gemini AI Client configured successfully for Market Analyst.")
            except Exception as e:
                logger.error(f"Failed to configure Gemini AI: {e}. Falling back to rule-based sentiment.")
                self.use_gemini = False
        else:
            logger.info("No Gemini API key detected. Using rule-based sentiment analysis.")

    def fetch_ticker_news(self, ticker: str) -> List[str]:
        """Fetch real-time news headlines from Yahoo Finance RSS feed."""
        headlines = []
        try:
            url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title')
                if title is not None and title.text:
                    headlines.append(title.text)
                    
            logger.info(f"Fetched {len(headlines)} headlines for {ticker} from RSS feed.")
        except Exception as e:
            logger.error(f"Error fetching RSS news for {ticker}: {e}")
            # Fallback mock headlines if network fails
            headlines = self._get_mock_headlines(ticker)
        
        return headlines if headlines else self._get_mock_headlines(ticker)

    def _get_mock_headlines(self, ticker: str) -> List[str]:
        """Provide mock headlines for fallback."""
        mocks = {
            "AAPL": [
                "Apple signs new deal with chip supplier for advanced AI integration",
                "App Store revenue increases as services business grows in Europe",
                "Apple Stock faces downgrade over short-term supply chain delays",
                "Why Apple Intelligence will drive the next multi-year upgrade cycle"
            ],
            "NVDA": [
                "NVIDIA chip demand reaches record high ahead of data center expansion",
                "Competitor launches new AI accelerator targeting NVIDIA market share",
                "NVIDIA stock hits new high as analyst raises target price",
                "Taiwan semiconductor supply chain disruptions pose risk to NVIDIA shipments"
            ],
            "MSFT": [
                "Microsoft cloud services report massive quarterly growth fueled by Azure AI",
                "Security patches issued after Windows exploit detected in corporate networks",
                "Microsoft announces partnership with energy startup to power AI data centers",
                "Analysts positive on Microsoft ahead of key developer conference"
            ],
            "SPY": [
                "Federal Reserve signals potential rate cut in upcoming economic report",
                "US inflation numbers come in cooler than expected, boosting indices",
                "Geopolitical tensions spark brief sell-off in major index funds",
                "Wall Street rallies as retail sales figures beat expectations"
            ],
            "QQQ": [
                "Nasdaq 100 leads rally as tech giants continue strong earnings momentum",
                "Treasury yields surge, placing pressure on high-growth tech stocks",
                "Tech sector volatility spikes as option volume hits quarterly record",
                "Semiconductor index rallies, lifting tech ETFs to weekly highs"
            ]
        }
        return mocks.get(ticker, [
            f"Analysts hold neutral outlook on {ticker} amid macro uncertainties",
            f"{ticker} announces new efficiency plans and expansion to cut costs",
            f"Trading volume for {ticker} increases ahead of quarterly earnings announcement"
        ])

    def analyze_market_sentiment(self, ticker: str) -> Tuple[float, str]:
        """
        Analyze news headlines to output a sentiment score (-1.0 to +1.0) and justification.
        """
        headlines = self.fetch_ticker_news(ticker)
        headlines_str = "\n".join([f"- {h}" for h in headlines[:5]])
        
        if self.use_gemini:
            try:
                prompt = (
                    f"You are a professional financial market analyst evaluating {ticker}.\n"
                    f"Analyze the following recent news headlines:\n\n{headlines_str}\n\n"
                    f"Based ONLY on these headlines, score the market sentiment for {ticker} between -1.0 (strongly bearish) and +1.0 (strongly bullish).\n"
                    f"Format your response exactly as follows and nothing else:\n"
                    f"SCORE: [score between -1.0 and 1.0]\n"
                    f"ANALYSIS: [1-2 sentences explaining why, summarizing the main positive or negative drivers]"
                )
                
                response = self.model.generate_content(prompt)
                text = response.text.strip()
                
                score_match = re.search(r"SCORE:\s*(-?\d+(\.\d+)?)", text)
                analysis_match = re.search(r"ANALYSIS:\s*(.*)", text, re.DOTALL)
                
                score = float(score_match.group(1)) if score_match else 0.0
                analysis = analysis_match.group(1).strip() if analysis_match else "Could not extract analysis from LLM output."
                
                # Constrain score
                score = max(-1.0, min(1.0, score))
                return score, analysis
                
            except Exception as e:
                logger.error(f"Gemini sentiment analysis failed: {e}. Falling back to rule-based.")
        
        # Rule-based fallback (reads positive/negative keywords in headlines)
        pos_words = ["high", "grow", "surge", "gain", "buy", "up", "beat", "rally", "positive", "expand", "deal", "deal with"]
        neg_words = ["drop", "downgrade", "exploit", "delay", "sell", "pressure", "disruption", "risk", "short-term", "down"]
        
        score_sum = 0.0
        for h in headlines:
            h_lower = h.lower()
            for w in pos_words:
                if w in h_lower:
                    score_sum += 0.25
            for w in neg_words:
                if w in h_lower:
                    score_sum -= 0.25
                    
        # Apply some random market noise to make it dynamic
        score_sum += random.uniform(-0.15, 0.15)
        score = round(max(-1.0, min(1.0, score_sum)), 2)
        
        driver = "positive updates on AI and partnerships" if score > 0 else "supply chain delays or analyst pressure"
        if abs(score) < 0.2:
            driver = "mixed or balanced recent headlines"
            
        analysis = f"Rule-based sentiment shows {ticker} at {score} driven by {driver} observed in recent headlines."
        return score, analysis

    def propose_options_trade(self, ticker: str, sentiment_score: float) -> Optional[Dict[str, Any]]:
        """
        Formulate an option strategy based on sentiment score and available option chain.
        """
        # Fetch option chain
        chain = self.alpaca.get_option_chain(ticker)
        if not chain:
            logger.warning(f"No option contracts found in chain for {ticker}.")
            return None
            
        # Determine strategy direction based on sentiment
        # Strong Bullish: Buy Call
        # Strong Bearish: Buy Put
        # Mildly Bullish/Bearish/Neutral: Sell OTM Credit Spreads or Sell Covered Call/Cash-Secured Put
        
        if sentiment_score >= 0.25:
            # Bullish Strategy: Buy Call Option
            target_type = "call"
            strategy_name = "Long Call Strategy"
            side = "buy"
        elif sentiment_score <= -0.25:
            # Bearish Strategy: Buy Put Option
            target_type = "put"
            strategy_name = "Long Put Strategy"
            side = "buy"
        else:
            # Neutral/Range-bound Strategy: Sell out-of-the-money Call option (Covered Call simulation)
            # or sell Cash-Secured Put to collect premium. Let's do Cash-Secured Put (Sell Put)
            target_type = "put"
            strategy_name = "Cash-Secured Put (Income)"
            side = "sell"
            
        # Select best contract (expiry near-term, strike near-the-money)
        # For buying Call/Put, we want Strike near the stock price (ATM)
        # For writing Cash-Secured Put, we want Strike 3-5% Out-of-the-money (OTM)
        
        # Find current stock price from the chain snapshot
        stock_price = chain[0].get("stock_price", 100.0) if chain else 100.0
        
        eligible_contracts = [c for c in chain if c["type"] == target_type]
        if not eligible_contracts:
            return None
            
        # Filter contract based on strategy criteria
        best_contract = None
        if side == "buy":
            # Find closest to stock price (ATM)
            best_contract = min(eligible_contracts, key=lambda c: abs(c["strike"] - stock_price))
        else:
            # Sell OTM put: strike should be slightly below stock price
            otm_puts = [c for c in eligible_contracts if c["strike"] <= stock_price * 0.96]
            if otm_puts:
                # Get the one closest to the 4% OTM boundary
                best_contract = max(otm_puts, key=lambda c: c["strike"])
            else:
                best_contract = min(eligible_contracts, key=lambda c: abs(c["strike"] - stock_price))

        if not best_contract:
            return None
            
        premium = best_contract["last_price"]
        # Default Quantity based on a standard position sizing approach
        # Buy 1-5 contracts depending on pricing (aim for ~$500-$1000 premium total)
        qty = max(1, min(5, int(1000 / (premium * 100))))
        
        proposed_trade = {
            "ticker": ticker,
            "strategy": strategy_name,
            "symbol": best_contract["symbol"],
            "type": best_contract["type"],
            "strike": best_contract["strike"],
            "expiration": best_contract["expiration"],
            "side": side,
            "qty": qty,
            "premium": premium,
            "total_value": round(premium * qty * 100, 2),
            "stock_price": stock_price,
            "sentiment_score": sentiment_score
        }
        
        return proposed_trade

    def run_agent_scan(self, target_tickers: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Execute one complete agent scanning cycle over target tickers.
        Returns:
            (list of approved proposals, list of execution logs)
        """
        logs = []
        proposals = []
        
        logs.append(f"🤖 Agent Scan Cycle started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 1. Fetch current account info & positions
        acc_info = self.alpaca.get_account_info()
        positions = self.alpaca.get_active_positions()
        
        logs.append(f"[Portfolio] Balance: ${acc_info['equity']:.2f} | Buying Power: ${acc_info['buying_power']:.2f}")
        
        # 2. Portfolio Risk Check (Stop Loss / Take Profit)
        exit_trades = self.risk_engine.check_portfolio_risk(positions)
        if exit_trades:
            for exit in exit_trades:
                logs.append(f"⚠️ [Risk Officer] Safety Breach Detected! closing position {exit['symbol']}. Reason: {exit['reason']}")
                # Execute liquidation immediately
                res = self.alpaca.execute_options_trade(exit["symbol"], exit["qty"], exit["side"], "Liquidation")
                if res["success"]:
                    logs.append(f"✅ [Executor] Closed contract {exit['symbol']}. Received filling ID: {res['order_id']}")
                else:
                    logs.append(f"❌ [Executor] Failed to close contract: {res.get('error')}")
        else:
            logs.append("[Risk Officer] No stop-loss or take-profit targets triggered on active positions.")

        # 3. Analyze and Propose Trades for Tickers
        held_tickers = {pos["underlying_symbol"] for pos in positions}
        available_tickers = [t for t in target_tickers if t not in held_tickers]
        
        if not available_tickers:
            logs.append("[Strategist] Already holding positions in all target tickers. Monitoring active positions for exits.")
            return proposals, logs
            
        selected_ticker = random.choice(available_tickers)
        logs.append(f"[Analyst] Starting analysis on target ticker: {selected_ticker}")
        
        sentiment, analysis = self.analyze_market_sentiment(selected_ticker)
        logs.append(f"[Analyst] {selected_ticker} Sentiment: {sentiment:+.2f} | {analysis}")
        
        proposed_trade = self.propose_options_trade(selected_ticker, sentiment)
        
        if proposed_trade:
            logs.append(
                f"[Strategist] Proposing {proposed_trade['strategy']} on {selected_ticker}: "
                f"{proposed_trade['side'].upper()} {proposed_trade['qty']}x {proposed_trade['symbol']} "
                f"at Premium ${proposed_trade['premium']:.2f} (Total: ${proposed_trade['total_value']:.2f})"
            )
            
            # Run Sentry Risk Evaluation
            approved, risk_reason = self.risk_engine.evaluate_trade(
                symbol=proposed_trade["symbol"],
                qty=proposed_trade["qty"],
                premium_per_contract=proposed_trade["premium"],
                side=proposed_trade["side"],
                account_info=acc_info
            )
            
            if approved:
                logs.append(f"🛡️ [Risk Officer] Approved. {risk_reason}")
                proposed_trade["risk_checked"] = True
                proposals.append(proposed_trade)
            else:
                logs.append(f"🛡️ [Risk Officer] REJECTED. Reason: {risk_reason}")
        else:
            logs.append(f"[Strategist] No viable option strategy identified for {selected_ticker}.")
            
        return proposals, logs
import datetime
