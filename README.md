### 🛡️ What is SentryTheta AI?
SentryTheta AI is an institutional-grade, multi-agent options trading platform built for the Alpaca AI Trading Hackathon. It solves the critical vulnerability of LLM financial trading: hallucinations and catastrophic account drawdowns.

### 🧠 Multi-Agent Architecture
1. **Market Analyst:** Analyzes Yahoo Finance RSS feeds using Google Gemini 1.5/2.0 Flash for directional sentiment scoring.
2. **Volatility Strategist:** Queries live Alpaca option chains and structures near-the-money Call/Put and Cash-Secured Put strategies.
3. **Sentry Risk Officer:** Deterministically enforces 5% max position sizing, a 3% daily drawdown circuit breaker, and automated Stop-Loss (-15%) / Take-Profit (+30%) liquidations.
4. **Trade Executor:** Transmits verified orders to Alpaca Paper Trading API or queues them for Copilot approval.

### 🌟 Key Features
- **Dual Mode:** 1-Click Toggle between Copilot (Human Approval) and Autopilot (Autonomous).
- **Interactive Web Dashboard:** Glassmorphism dark theme, real-time WebSockets, searchable dropdown of 6,100+ optionable stocks, and a 4-step guided setup checklist.
- **Persistence & Extensibility:** SQLite database state preservation (`sentrytheta.db`) and Model Context Protocol (MCP) server integration for external LLM tools.
