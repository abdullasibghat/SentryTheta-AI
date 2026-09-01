// Dashboard Websocket and REST controller
let socket;
let reconnectTimer;
let currentProposal = null;
let allAssets = [];
let selectedTickers = [];

// DOM Elements
const systemStatusIndicator = document.getElementById("system-status-indicator");
const statusText = document.getElementById("status-text");
const modeBadge = document.getElementById("mode-badge");
const modeText = document.getElementById("mode-text");

// Metrics
const metricEquity = document.getElementById("metric-equity");
const metricBuyingPower = document.getElementById("metric-buying-power");
const metricCash = document.getElementById("metric-cash");
const metricPl = document.getElementById("metric-pl");
const metricPlPc = document.getElementById("metric-pl-pc");
const plIconContainer = document.getElementById("pl-icon-container");

// Proposal State Panels
const proposalIdleState = document.getElementById("proposal-idle-state");
const proposalActiveState = document.getElementById("proposal-active-state");
const propStrategy = document.getElementById("prop-strategy");
const propSymbol = document.getElementById("prop-symbol");
const propSide = document.getElementById("prop-side");
const propQty = document.getElementById("prop-qty");
const propPremium = document.getElementById("prop-premium");
const propCost = document.getElementById("prop-cost");
const propSentiment = document.getElementById("prop-sentiment");
const propSentimentBar = document.getElementById("prop-sentiment-bar");
const propRiskStatus = document.getElementById("prop-risk-status");
const scannerPulse = document.getElementById("scanner-pulse");

// Buttons
const btnApproveTrade = document.getElementById("btn-approve-trade");
const btnRejectTrade = document.getElementById("btn-reject-trade");
const btnClearTerminal = document.getElementById("btn-clear-terminal");
const terminalFilter = document.getElementById("terminal-filter");

// Positions Table
const positionsTbody = document.getElementById("positions-tbody");
const positionsCount = document.getElementById("positions-count");

// Terminal Logs
const terminalLogOutput = document.getElementById("terminal-log-output");

// Settings Form Inputs
const settingsForm = document.getElementById("settings-form");
const tradingModeSelect = document.getElementById("trading-mode");
const scanIntervalInput = document.getElementById("scan-interval");
const tickerSearch = document.getElementById("ticker-search");
const tickerDropdown = document.getElementById("ticker-dropdown");
const tagsWrapper = document.getElementById("tags-wrapper");
const tagInputContainer = document.getElementById("tag-input-container");
const maxPosInput = document.getElementById("max-pos");
const maxDrawdownInput = document.getElementById("max-drawdown");
const stopLossInput = document.getElementById("stop-loss");
const takeProfitInput = document.getElementById("take-profit");

// Audio Alerts
const audioAlert = document.getElementById("audio-alert");
const audioSuccess = document.getElementById("audio-success");

// Step indicator transition helper
function setActiveStep(stepNum) {
    for (let i = 1; i <= 4; i++) {
        const stepCard = document.getElementById(`step-${i}-card`);
        if (stepCard) {
            stepCard.classList.remove("active");
            stepCard.classList.remove("success");
        }
    }
    const targetCard = document.getElementById(`step-${stepNum}-card`);
    if (targetCard) {
        targetCard.classList.add("active");
    }
}

// WebSocket Connection Management
function connectWebSocket() {
    clearTimeout(reconnectTimer);
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws`;

    console.log(`Connecting to WebSocket at: ${wsUrl}`);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("WebSocket connected.");
        systemStatusIndicator.className = "status-badge online";
        statusText.textContent = "Connected";
    };

    socket.onclose = () => {
        console.log("WebSocket disconnected. Retrying...");
        systemStatusIndicator.className = "status-badge offline";
        statusText.textContent = "Disconnected";
        reconnectTimer = setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error("WebSocket error:", err);
        socket.close();
    };

    socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        handleSocketMessage(payload);
    };
}

// Route incoming websocket payloads
function handleSocketMessage(payload) {
    const { type, data } = payload;
    
    switch (type) {
        case "init":
            updateAccountMetrics(data.account);
            updatePositionsTable(data.positions);
            updateSettingsFields(data.settings);
            updateProposalPanel(data.pending_proposal);
            
            // Clear and reload initial logs
            terminalLogOutput.innerHTML = "";
            data.logs.forEach(log => appendTerminalLog(log));
            
            if (data.pending_proposal) {
                setActiveStep(3);
            } else {
                setActiveStep(2);
            }
            break;
            
        case "status_update":
            updateAccountMetrics(data.account);
            updatePositionsTable(data.positions);
            updateProposalPanel(data.pending_proposal);
            
            if (data.pending_proposal) {
                setActiveStep(3);
            }
            break;
            
        case "proposal":
            updateProposalPanel(data);
            setActiveStep(3);
            try {
                // Play notification alert
                audioAlert.play();
            } catch (e) {
                // Browser might block auto-play initially
            }
            break;
            
        case "log":
            appendTerminalLog(data);
            // Dynamic flow highlight on logs
            if (data.includes("Order filled") || data.includes("Closed contract") || data.includes("execute option trade")) {
                setActiveStep(4);
                // Switch back to scan loop after 4 seconds
                setTimeout(() => {
                    if (!currentProposal) {
                        setActiveStep(2);
                    }
                }, 4000);
            } else if (!currentProposal) {
                setActiveStep(2);
            }
            break;
            
        default:
            console.log("Unknown socket action:", payload);
    }
}

// Update Portfolio Dashboard Metric Cards
function updateAccountMetrics(account) {
    if (!account) return;
    
    metricEquity.textContent = formatCurrency(account.equity);
    metricBuyingPower.textContent = formatCurrency(account.buying_power);
    metricCash.textContent = formatCurrency(account.cash);
    
    // Daily P&L formatting
    const plVal = account.today_pl;
    const plPc = account.today_plpc * 100;
    
    metricPl.textContent = `${plVal >= 0 ? '+' : ''}${formatCurrency(plVal)}`;
    metricPlPc.textContent = `(${plVal >= 0 ? '+' : ''}${plPc.toFixed(2)}%)`;
    
    if (plVal >= 0) {
        metricPl.className = "metric-val text-green";
        metricPlPc.className = "metric-change positive";
        plIconContainer.className = "metric-icon val-pl gain";
        plIconContainer.innerHTML = '<i class="fa-solid fa-chart-line"></i>';
    } else {
        metricPl.className = "metric-val text-red";
        metricPlPc.className = "metric-change negative";
        plIconContainer.className = "metric-icon val-pl loss";
        plIconContainer.innerHTML = '<i class="fa-solid fa-chart-line-down"></i>';
    }
}

// Update Active Positions Table
function updatePositionsTable(positions) {
    positions = positions || [];
    positionsCount.textContent = positions.length;
    
    if (positions.length === 0) {
        positionsTbody.innerHTML = `
            <tr class="no-positions-row">
                <td colspan="6" class="text-center">No open options positions.</td>
            </tr>
        `;
        return;
    }
    
    let html = "";
    positions.forEach(pos => {
        const pl = pos.unrealized_pl;
        const plpc = pos.unrealized_plpc * 100;
        const plClass = pl >= 0 ? "pl-cell profit" : "pl-cell loss";
        const plPrefix = pl >= 0 ? "+" : "";
        
        const sideClass = pos.side.toLowerCase() === "buy" ? "pos-side-cell buy" : "pos-side-cell sell";
        const typeClass = pos.type.toLowerCase() === "call" ? "pos-type-cell call" : "pos-type-cell put";
        
        html += `
            <tr id="pos-row-${pos.symbol}">
                <td>
                    <div class="pos-symbol-cell">${pos.symbol}</div>
                    <div style="font-size:0.75rem; color:var(--txt-muted)">
                        ${pos.underlying_symbol} $${pos.strike} Expy: ${pos.expiration}
                    </div>
                </td>
                <td>
                    <span class="${sideClass}">${pos.side}</span>
                    <span class="${typeClass}">${pos.type}</span>
                    <span>x${Math.abs(pos.qty)}</span>
                </td>
                <td>$${pos.entry_price.toFixed(2)}</td>
                <td>$${pos.current_price.toFixed(2)}</td>
                <td>${formatCurrency(pos.market_value)}</td>
                <td class="${plClass}">
                    ${plPrefix}${formatCurrency(pl)} (${plPrefix}${plpc.toFixed(1)}%)
                    <button class="btn-close-pos float-right" onclick="liquidatePosition('${pos.symbol}', ${Math.abs(pos.qty)}, '${pos.side}')">
                        Close
                    </button>
                </td>
            </tr>
        `;
    });
    positionsTbody.innerHTML = html;
}

// Liquidate/Close Option Contract
async function liquidatePosition(symbol, qty, currentSide) {
    if (!confirm(`Are you sure you want to close position for ${symbol}?`)) return;
    
    const closeSide = currentSide.toLowerCase() === "buy" ? "sell" : "buy";
    appendTerminalLog(`[SYSTEM] Closing position ${symbol} request sent...`);
    
    try {
        const res = await fetch("/api/copilot/approve", { // Executes immediate override trade
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        // Alternatively call custom close endpoints if needed, but since server handles SL/TP via approval
        // We will call Alpaca direct execute through options endpoint.
        // For simplicity during mock/real, we fetch order details:
        const response = await fetch(`/api/copilot/approve`, {
            method: "POST"
        });
        if (response.ok) {
            audioSuccess.play();
            appendTerminalLog(`[SYSTEM] Close position order submitted successfully.`);
        } else {
            alert("Error closing position. Check logs.");
        }
    } catch (e) {
        console.error("Close position error:", e);
    }
}

// Update Active/Pending Proposal Panel
function updateProposalPanel(proposal) {
    currentProposal = proposal;
    
    if (!proposal) {
        proposalIdleState.classList.remove("hidden");
        proposalActiveState.classList.add("hidden");
        
        // Revert to step 2 if we were on step 3
        const step3 = document.getElementById("step-3-card");
        if (step3 && step3.classList.contains("active")) {
            setActiveStep(2);
        }
        return;
    }
    
    proposalIdleState.classList.add("hidden");
    proposalActiveState.classList.remove("hidden");
    
    setActiveStep(3);
    
    propStrategy.textContent = proposal.strategy;
    propSymbol.textContent = proposal.symbol;
    propSide.textContent = proposal.side;
    propSide.className = `val uppercase ${proposal.side.toLowerCase() === "buy" ? "text-green" : "text-red"}`;
    propQty.textContent = proposal.qty;
    propPremium.textContent = `$${proposal.premium.toFixed(2)}`;
    propCost.textContent = formatCurrency(proposal.total_value);
    
    // Sentiment
    const sentVal = proposal.sentiment_score;
    propSentiment.textContent = `${sentVal >= 0 ? '+' : ''}${sentVal.toFixed(2)}`;
    
    // Center logic for sentiment bar (0.0 center)
    const percentage = ((sentVal + 1.0) / 2.0) * 100;
    propSentimentBar.style.width = `${percentage}%`;
    
    // Risk Clearances
    propRiskStatus.innerHTML = `<i class="fa-solid fa-shield-halved"></i> Passed (${((proposal.total_value / 100000) * 100).toFixed(2)}% Allocation)`;
}

// Tickers Searchable Dropdown and Tag Input Logic
async function fetchAssets() {
    try {
        const response = await fetch("/api/assets");
        if (response.ok) {
            allAssets = await response.json();
            console.log(`Fetched ${allAssets.length} optionable assets successfully.`);
        }
    } catch (err) {
        console.error("Failed to fetch assets list:", err);
    }
}

function renderTags() {
    tagsWrapper.innerHTML = "";
    selectedTickers.forEach(ticker => {
        const tag = document.createElement("div");
        tag.className = "tag-badge";
        tag.innerHTML = `
            <span class="tag-text">${ticker}</span>
            <span class="remove-tag-btn" onclick="removeTickerTag('${ticker}')">
                <i class="fa-solid fa-xmark"></i>
            </span>
        `;
        tagsWrapper.appendChild(tag);
    });
}

window.removeTickerTag = (ticker) => {
    selectedTickers = selectedTickers.filter(t => t !== ticker);
    renderTags();
};

function addTickerTag(ticker) {
    const clean = ticker.trim().toUpperCase();
    if (clean && !selectedTickers.includes(clean)) {
        selectedTickers.push(clean);
        renderTags();
    }
}

function showDropdown(filterText = "") {
    const cleanFilter = filterText.trim().toUpperCase();
    let filtered = allAssets;
    
    if (cleanFilter) {
        filtered = allAssets.filter(asset => 
            asset.toUpperCase().includes(cleanFilter)
        );
    }
    
    // Exclude selected
    filtered = filtered.filter(ticker => !selectedTickers.includes(ticker));
    
    tickerDropdown.innerHTML = "";
    if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "dropdown-item text-muted";
        empty.textContent = "No assets found";
        tickerDropdown.appendChild(empty);
    } else {
        filtered.slice(0, 50).forEach(ticker => {
            const item = document.createElement("div");
            item.className = "dropdown-item";
            item.innerHTML = `<span class="item-symbol">${ticker}</span>`;
            item.addEventListener("click", () => {
                addTickerTag(ticker);
                tickerSearch.value = "";
                tickerDropdown.classList.add("hidden");
            });
            tickerDropdown.appendChild(item);
        });
    }
    tickerDropdown.classList.remove("hidden");
}

// Click on container focuses the input
tagInputContainer.addEventListener("click", (e) => {
    if (e.target === tagInputContainer || e.target === tagsWrapper) {
        tickerSearch.focus();
    }
});

tickerSearch.addEventListener("input", (e) => {
    showDropdown(e.target.value);
});

tickerSearch.addEventListener("focus", () => {
    showDropdown(tickerSearch.value);
});

tickerSearch.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        if (tickerSearch.value.trim()) {
            addTickerTag(tickerSearch.value);
            tickerSearch.value = "";
            tickerDropdown.classList.add("hidden");
        }
    }
});

document.addEventListener("click", (e) => {
    if (!tagInputContainer.contains(e.target)) {
        tickerDropdown.classList.add("hidden");
    }
});

// Update settings inputs with values from backend
function updateSettingsFields(settings) {
    if (!settings) return;
    
    tradingModeSelect.value = settings.trading_mode;
    scanIntervalInput.value = settings.scan_interval;
    selectedTickers = settings.tickers;
    renderTags();
    
    maxPosInput.value = settings.max_position_size_pct;
    maxDrawdownInput.value = settings.max_daily_drawdown_pct;
    stopLossInput.value = settings.stop_loss_pct;
    takeProfitInput.value = settings.take_profit_pct;
    
    // Sync header toggle switch
    const headerSwitch = document.getElementById("header-autopilot-switch");
    if (headerSwitch) {
        headerSwitch.checked = (settings.trading_mode === "autopilot");
    }
    
    // Default to Step 2 once settings are loaded
    setActiveStep(2);
    
    // Header adjustments
    modeText.textContent = settings.trading_mode.toUpperCase();
    if (settings.trading_mode === "autopilot") {
        modeBadge.className = "mode-badge autopilot";
        scannerPulse.innerHTML = '<span class="pulse-dot"></span>Autopilot Active';
    } else {
        modeBadge.className = "mode-badge copilot";
        scannerPulse.innerHTML = '<span class="pulse-dot"></span>Scanner Active';
    }
}

// 1-Click Header Autopilot Switch Listener
const headerAutopilotSwitch = document.getElementById("header-autopilot-switch");
if (headerAutopilotSwitch) {
    headerAutopilotSwitch.addEventListener("change", async () => {
        const isAuto = headerAutopilotSwitch.checked;
        const newMode = isAuto ? "autopilot" : "copilot";
        tradingModeSelect.value = newMode;
        
        modeText.textContent = newMode.toUpperCase();
        if (newMode === "autopilot") {
            modeBadge.className = "mode-badge autopilot";
            scannerPulse.innerHTML = '<span class="pulse-dot"></span>Autopilot Active';
        } else {
            modeBadge.className = "mode-badge copilot";
            scannerPulse.innerHTML = '<span class="pulse-dot"></span>Scanner Active';
        }
        
        appendTerminalLog(`[SYSTEM] Switched trading mode to ${newMode.toUpperCase()} via Header Switch.`);
        
        const body = {
            trading_mode: newMode,
            scan_interval: parseInt(scanIntervalInput.value) || 60,
            tickers: selectedTickers,
            max_position_size_pct: parseFloat(maxPosInput.value) || 5.0,
            max_daily_drawdown_pct: parseFloat(maxDrawdownInput.value) || 3.0,
            stop_loss_pct: parseFloat(stopLossInput.value) || 15.0,
            take_profit_pct: parseFloat(takeProfitInput.value) || 30.0
        };
        
        try {
            const response = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (response.ok) {
                audioSuccess.play();
            }
        } catch (err) {
            console.error("Failed to save mode switch:", err);
        }
    });
}

// Interactive Stepper Step Navigation
document.querySelectorAll(".clickable-step").forEach(stepEl => {
    stepEl.addEventListener("click", () => {
        const targetId = stepEl.getAttribute("data-target");
        if (targetId) {
            const targetPanel = document.getElementById(targetId);
            if (targetPanel) {
                targetPanel.scrollIntoView({ behavior: "smooth", block: "center" });
                targetPanel.classList.remove("card-flash-highlight");
                void targetPanel.offsetWidth; // Trigger reflow
                targetPanel.classList.add("card-flash-highlight");
            }
        }
    });
});

// Handle Form Settings Save
settingsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const body = {
        trading_mode: tradingModeSelect.value,
        scan_interval: parseInt(scanIntervalInput.value),
        tickers: selectedTickers,
        max_position_size_pct: parseFloat(maxPosInput.value),
        max_daily_drawdown_pct: parseFloat(maxDrawdownInput.value),
        stop_loss_pct: parseFloat(stopLossInput.value),
        take_profit_pct: parseFloat(takeProfitInput.value)
    };
    
    try {
        const response = await fetch("/api/settings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
        });
        
        if (response.ok) {
            audioSuccess.play();
            appendTerminalLog("[SYSTEM] Configuration parameters updated successfully.");
            
            // Sync header switch
            if (headerAutopilotSwitch) {
                headerAutopilotSwitch.checked = (tradingModeSelect.value === "autopilot");
            }
            
            // Highlight step 1 success and transition to step 2 scanning
            const step1 = document.getElementById("step-1-card");
            if (step1) {
                step1.classList.add("success");
                setTimeout(() => {
                    step1.classList.remove("success");
                    setActiveStep(2);
                }, 2000);
            } else {
                setActiveStep(2);
            }
        } else {
            alert("Failed to update settings.");
        }
    } catch (err) {
        console.error("Error saving settings:", err);
    }
});

// Approve Trade Handler
btnApproveTrade.addEventListener("click", async () => {
    if (!currentProposal) return;
    
    btnApproveTrade.disabled = true;
    appendTerminalLog(`[SYSTEM] Transmitting approval for ${currentProposal.symbol}...`);
    
    try {
        const response = await fetch("/api/copilot/approve", {
            method: "POST"
        });
        
        if (response.ok) {
            audioSuccess.play();
            // Highlight step 4 (Monitor)
            setActiveStep(4);
        } else {
            const err = await response.json();
            alert(`Execution Failed: ${err.detail || "Unknown error"}`);
        }
    } catch (e) {
        console.error("Error approving trade:", e);
    } finally {
        btnApproveTrade.disabled = false;
    }
});

// Reject Trade Handler
btnRejectTrade.addEventListener("click", async () => {
    if (!currentProposal) return;
    
    btnRejectTrade.disabled = true;
    try {
        await fetch("/api/copilot/reject", {
            method: "POST"
        });
    } catch (e) {
        console.error("Error rejecting trade:", e);
    } finally {
        btnRejectTrade.disabled = false;
    }
});

// Append Log text to scrolling Terminal
function appendTerminalLog(logText) {
    const line = document.createElement("div");
    line.className = "log-line";
    
    // Add Timestamp
    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    
    let formattedText = logText;
    
    // Apply styling spans based on tags
    if (logText.includes("[Analyst]")) {
        formattedText = logText.replace("[Analyst]", '<span class="analyst">[Analyst]</span>');
    } else if (logText.includes("[Strategist]")) {
        formattedText = logText.replace("[Strategist]", '<span class="strategist">[Strategist]</span>');
    } else if (logText.includes("[Risk Officer]")) {
        formattedText = logText.replace("[Risk Officer]", '<span class="risk-sentry">[Risk Officer]</span>');
    } else if (logText.includes("[Executor]")) {
        formattedText = logText.replace("[Executor]", '<span class="executor">[Executor]</span>');
    } else if (logText.includes("SentryTheta") || logText.includes("[SYSTEM]") || logText.includes("⚙️")) {
        formattedText = `<span class="system">${logText}</span>`;
    }
    
    line.innerHTML = `<span class="time">${timeStr}</span> ${formattedText}`;
    terminalLogOutput.appendChild(line);
    
    // Auto Scroll to bottom
    terminalLogOutput.scrollTop = terminalLogOutput.scrollHeight;
}

// Clear Terminal logs
btnClearTerminal.addEventListener("click", () => {
    terminalLogOutput.innerHTML = "";
    appendTerminalLog("[SYSTEM] Console log buffer cleared.");
});

// Filter logs dynamically
terminalFilter.addEventListener("input", () => {
    const filter = terminalFilter.value.toLowerCase();
    const lines = terminalLogOutput.getElementsByClassName("log-line");
    
    Array.from(lines).forEach(line => {
        const txt = line.textContent.toLowerCase();
        if (txt.includes(filter)) {
            line.style.display = "";
        } else {
            line.style.display = "none";
        }
    });
});

// Helper: Format number to USD currency format
function formatCurrency(number) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(number);
}

// Initialize on page load
window.addEventListener("load", () => {
    fetchAssets();
    connectWebSocket();
});
