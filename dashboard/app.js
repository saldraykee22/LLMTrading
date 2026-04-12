/**
 * LLM Trading System — Dashboard Application
 * Real-time monitoring and control panel
 */

// ── State ─────────────────────────────────────────────────
const state = {
    portfolio: {
        equity: 10000,
        cash: 10000,
        totalPnl: 0,
        drawdown: 0,
        positions: [],
    },
    sentiment: {
        score: 0,
        signal: 'neutral',
        confidence: 0,
        risk: 0,
    },
    regime: {
        state: 'normal',
        vix: 0,
    },
    benchmark: {
        symbol: 'BTC/USDT',
        return: 0,
        alpha: 0,
    },
    trades: [],
    logs: [],
};

// ── API Configuration ─────────────────────────────────────
const API_KEY = window.DASHBOARD_API_KEY || localStorage.getItem('llm_dashboard_api_key') || null;

function apiFetch(url, options = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (API_KEY) {
        headers['X-API-Key'] = API_KEY;
    }
    return fetch(url, { ...options, headers: { ...headers, ...options.headers } });
}

// ── Time Display ──────────────────────────────────────────
function updateTime() {
    const now = new Date();
    const el = document.getElementById('currentTime');
    if (el) {
        el.textContent = now.toLocaleTimeString('tr-TR', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        }) + ' UTC+3';
    }
}
setInterval(updateTime, 1000);
updateTime();

// ── Data Loading ──────────────────────────────────────────
async function loadLatestAnalysis() {
    try {
        const [portfolioRes, statusRes, tradesRes, allocRes, benchRes] = await Promise.all([
            apiFetch('/api/portfolio'),
            apiFetch('/api/status'),
            apiFetch('/api/trades?limit=10'),
            apiFetch('/api/portfolio_allocation'),
            apiFetch('/api/benchmark'),
        ]);

        if (portfolioRes.ok) {
            const portfolio = await portfolioRes.json();
            updateDashboard(portfolio);
        }

        if (tradesRes.ok) {
            const tradesData = await tradesRes.json();
            updateTradesTable(tradesData.trades || []);
        }

        if (statusRes.ok) {
            const status = await statusRes.json();
            const statusEl = document.getElementById('systemStatus');
            if (statusEl) {
                statusEl.querySelector('span:last-child').textContent =
                    status.portfolio_loaded ? 'Aktif' : 'Bekleniyor';
            }
        }

        if (allocRes.ok) {
            const allocData = await allocRes.json();
            updatePortfolioAllocation(allocData);
        }

        if (benchRes.ok) {
            const benchData = await benchRes.json();
            updateBenchmark(benchData);
        }
    } catch (e) {
        console.log('API bağlantısı yok, demo verisi kullanılıyor');
        updateDashboard(getDemoData());
    }
}

function getDemoData() {
    return {
        portfolio: {
            equity: 10247.83,
            cash: 7834.21,
            totalPnl: 247.83,
            dailyPnl: 52.10,
            drawdown: 0.012,
            positions: [
                {
                    symbol: 'BTC/USDT',
                    side: 'long',
                    entry_price: 64250.00,
                    amount: 0.035,
                    unrealized_pnl: 87.50,
                    current_price: 66750.00,
                },
            ],
        },
        sentiment: {
            sentiment_score: 0.42,
            signal: 'bullish',
            confidence: 0.78,
            risk_score: 0.35,
        },
        debate_result: {
            consensus_score: 0.38,
            adjusted_signal: 'bullish',
            winner: 'bull',
        },
        risk_assessment: {
            decision: 'approved',
            vix_current: 18.5,
            vix_sma: 16.2,
        },
        regime: 'normal',
        trade_decision: {
            action: 'hold',
            symbol: 'BTC/USDT',
            reasoning: 'Mevcut pozisyon aktif, ek pozisyon gerekmiyor',
        },
        messages: [
            { role: 'coordinator', content: 'Analiz başlatıldı: BTC/USDT' },
            { role: 'research_analyst', content: 'Duyarlılık: bullish (0.42), Güven: 0.78' },
            { role: 'debate', content: 'Bull vs Bear: Bull kazandı, konsensüs 0.38' },
            { role: 'risk_manager', content: 'Risk onaylandı — tüm kontroller geçti' },
            { role: 'trader', content: 'Karar: HOLD — mevcut pozisyon aktif' },
        ],
    };
}

// ── Dashboard Update ──────────────────────────────────────
function updateDashboard(data) {
    // Portfolio
    if (data.portfolio) {
        updateElement('equity', formatCurrency(data.portfolio.equity));
        updateElement('cash', formatCurrency(data.portfolio.cash));

        const pnl = data.portfolio.totalPnl || 0;
        const pnlEl = document.getElementById('totalPnl');
        if (pnlEl) {
            pnlEl.textContent = formatCurrency(pnl);
            pnlEl.style.color = pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
        }

        const dd = data.portfolio.drawdown || 0;
        const ddEl = document.getElementById('drawdown');
        if (ddEl) {
            ddEl.textContent = (dd * 100).toFixed(2) + '%';
            ddEl.style.color = dd > 0.1 ? 'var(--accent-red)' : 'var(--text-primary)';
        }

        // Positions
        updatePositions(data.portfolio.positions || []);
    }

    // Sentiment
    if (data.sentiment) {
        updateSentiment(data.sentiment);
    }

    // Regime
    if (data.regime) {
        updateElement('regimeValue', data.regime.toUpperCase());
    }

    // Risk
    if (data.risk_assessment) {
        const vix = data.risk_assessment.vix_current || 0;
        updateElement('vixValue', vix.toFixed(1));
        const vixBar = document.getElementById('vixBar');
        if (vixBar) vixBar.style.width = Math.min(vix / 50 * 100, 100) + '%';
    }

    // Agent Messages
    if (data.messages) {
        data.messages.forEach(msg => addLogEntry(msg.role, msg.content));
    }

    // Status
    const statusEl = document.getElementById('systemStatus');
    if (statusEl) {
        statusEl.querySelector('span:last-child').textContent = 'Aktif';
        statusEl.style.borderColor = 'rgba(16, 185, 129, 0.3)';
    }
}

function updatePositions(positions) {
    const list = document.getElementById('positionsList');
    const count = document.getElementById('positionCount');
    if (!list) return;

    count.textContent = positions.length;

    if (positions.length === 0) {
        list.innerHTML = '<div class="empty-state">Açık pozisyon yok</div>';
        return;
    }

    list.innerHTML = positions.map(pos => {
        const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
        const sideClass = pos.side === 'long' ? 'pos-long' : 'pos-short';
        return `
            <div class="position-item">
                <span class="pos-symbol">${pos.symbol}</span>
                <span class="pos-side ${sideClass}">${pos.side}</span>
                <span>${pos.amount.toFixed(4)}</span>
                <span>@ ${pos.entry_price.toLocaleString()}</span>
                <span class="pos-pnl ${pnlClass}">
                    ${pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                </span>
            </div>
        `;
    }).join('');
}

function updateSentiment(sentiment) {
    const score = sentiment.sentiment_score || 0;
    const position = ((score + 1) / 2) * 100; // -1..1 → 0..100%

    const fill = document.getElementById('gaugeFill');
    const value = document.getElementById('sentimentValue');
    if (fill) fill.style.left = position + '%';
    if (value) {
        value.style.left = position + '%';
        value.textContent = score.toFixed(2);
        value.style.color = score > 0.3 ? 'var(--accent-green)' :
                            score < -0.3 ? 'var(--accent-red)' : 'var(--text-primary)';
    }

    const signalEl = document.getElementById('sentimentSignal');
    if (signalEl) {
        signalEl.textContent = (sentiment.signal || 'neutral').toUpperCase();
        signalEl.className = 'signal-badge ' + (sentiment.signal || 'neutral');
    }

    updateElement('sentimentConfidence', ((sentiment.confidence || 0) * 100).toFixed(0) + '%');
    updateElement('sentimentRisk', ((sentiment.risk_score || 0) * 100).toFixed(0) + '%');
}

function updateTradesTable(trades) {
    const tbody = document.getElementById('tradesBody');
    if (!tbody) return;

    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Henüz işlem yok</td></tr>';
        return;
    }

    tbody.innerHTML = trades.slice(-10).reverse().map(trade => {
        const pnl = trade.pnl || 0;
        const pnlClass = pnl >= 0 ? 'positive' : 'negative';
        const sideClass = trade.side === 'long' ? 'pos-long' : 'pos-short';
        const time = trade.exit_time ? new Date(trade.exit_time).toLocaleTimeString('tr-TR', {
            hour: '2-digit', minute: '2-digit'
        }) : '—';
        return `
            <tr>
                <td>${time}</td>
                <td>${trade.symbol || '—'}</td>
                <td><span class="pos-side ${sideClass}">${trade.side || '—'}</span></td>
                <td>${trade.entry_price ? trade.entry_price.toFixed(2) : '—'}</td>
                <td>${trade.exit_price ? trade.exit_price.toFixed(2) : '—'}</td>
                <td class="pos-pnl ${pnlClass}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</td>
            </tr>
        `;
    }).join('');
}

// ── Portfolio Allocation ──────────────────────────────────
function updatePortfolioAllocation(data) {
    const content = document.getElementById('allocationContent');
    const statusEl = document.getElementById('allocStatus');
    if (!content) return;

    if (!data || data.status === 'no_allocation') {
        content.innerHTML = '<div class="empty-state">Portföy analizi bekleniyor</div>';
        if (statusEl) statusEl.textContent = '—';
        return;
    }

    if (data.status === 'no_qualified_assets') {
        content.innerHTML = `<div class="empty-state">Kalifiye varlık bulunamadı<br><small>${data.reason || ''}</small></div>`;
        if (statusEl) {
            statusEl.textContent = 'RED';
            statusEl.style.color = 'var(--accent-red)';
        }
        return;
    }

    if (statusEl) {
        statusEl.textContent = data.allocations ? Object.keys(data.allocations).length + ' VARLIK' : '—';
        statusEl.style.color = 'var(--accent-green)';
    }

    const allocations = data.allocations || {};
    const details = data.asset_details || {};
    const allScores = data.all_scores || {};

    let html = '<div class="allocation-bars">';

    for (const [symbol, weight] of Object.entries(allocations)) {
        const pct = (weight * 100).toFixed(1);
        const d = details[symbol] || {};
        const score = d.composite_score || 0;
        const scoreColor = score > 0.1 ? 'var(--accent-green)' : score < -0.1 ? 'var(--accent-red)' : 'var(--text-secondary)';
        const trend = d.trend || '—';
        const confidence = d.sentiment_confidence ? (d.sentiment_confidence * 100).toFixed(0) + '%' : '—';

        html += `
            <div class="alloc-bar">
                <div class="alloc-bar-header">
                    <span class="alloc-symbol">${symbol}</span>
                    <span class="alloc-weight">${pct}%</span>
                </div>
                <div class="alloc-bar-track">
                    <div class="alloc-bar-fill" style="width: ${pct}%; background: ${scoreColor}"></div>
                </div>
                <div class="alloc-bar-details">
                    <span>Skor: <strong style="color: ${scoreColor}">${score >= 0 ? '+' : ''}${score.toFixed(3)}</strong></span>
                    <span>Trend: <strong>${trend}</strong></span>
                    <span>Güven: <strong>${confidence}</strong></span>
                </div>
            </div>
        `;
    }

    html += '</div>';

    // CVaR info
    const cvar = data.cvar_info || {};
    if (cvar.cvar !== undefined) {
        html += `
            <div class="alloc-cvar">
                <div class="cvar-row">
                    <span>CVaR</span>
                    <span>${(cvar.cvar * 100).toFixed(2)}%</span>
                </div>
                <div class="cvar-row">
                    <span>VaR</span>
                    <span>${(cvar.var * 100).toFixed(2)}%</span>
                </div>
                <div class="cvar-row">
                    <span>Beklenen Getiri</span>
                    <span style="color: ${cvar.expected_return >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}">
                        ${(cvar.expected_return * 100).toFixed(2)}%
                    </span>
                </div>
            </div>
        `;
    }

    // All scores
    const excluded = Object.keys(allScores).filter(s => !allocations[s]);
    if (excluded.length > 0) {
        html += '<div class="alloc-excluded"><strong>Dışlananlar:</strong> ';
        html += excluded.map(s => {
            const sc = allScores[s].composite_score;
            return `<span style="color: ${sc >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}">${s} (${sc >= 0 ? '+' : ''}${sc.toFixed(3)})</span>`;
        }).join(', ');
        html += '</div>';
    }

    content.innerHTML = html;
}

function updateBenchmark(data) {
    const symbolEl = document.getElementById('benchmarkSymbol');
    const returnEl = document.getElementById('benchmarkReturn');
    const alphaEl = document.getElementById('alphaValue');

    if (symbolEl) symbolEl.textContent = data.benchmark_symbol || 'BTC/USDT';

    if (returnEl) {
        const benchRet = (data.benchmark_return || 0) * 100;
        returnEl.textContent = benchRet.toFixed(2) + '%';
        returnEl.style.color = benchRet >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
    }

    if (alphaEl) {
        const alpha = (data.alpha || 0) * 100;
        alphaEl.textContent = (alpha >= 0 ? '+' : '') + alpha.toFixed(2) + '%';
        alphaEl.style.color = alpha >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
    }
}

// ── Activity Log ──────────────────────────────────────────
function addLogEntry(role, message) {
    const log = document.getElementById('activityLog');
    if (!log) return;

    const roleMap = {
        coordinator: { label: 'Koord.', class: 'log-coordinator' },
        research_analyst: { label: 'Analist', class: 'log-analyst' },
        debate: { label: 'Tartışma', class: 'log-debate' },
        risk_manager: { label: 'Risk', class: 'log-risk' },
        trader: { label: 'İşlemci', class: 'log-trader' },
        system: { label: 'Sistem', class: 'log-system' },
    };

    const info = roleMap[role] || roleMap.system;
    const time = new Date().toLocaleTimeString('tr-TR', {
        hour: '2-digit',
        minute: '2-digit',
    });

    const entry = document.createElement('div');
    entry.className = `log-entry ${info.class}`;
    entry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-agent">${info.label}</span>
        <span class="log-message">${escapeHtml(message.substring(0, 200))}</span>
    `;

    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;

    // Max 50 kayıt tut
    while (log.children.length > 50) {
        log.removeChild(log.firstChild);
    }
}

function clearLog() {
    const log = document.getElementById('activityLog');
    if (log) {
        log.innerHTML = '';
        addLogEntry('system', 'Log temizlendi');
    }
}

// ── Utilities ─────────────────────────────────────────────
function updateElement(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function formatCurrency(val) {
    return '$' + (val || 0).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Chart.js Instances ────────────────────────────────────
let priceChart = null;
let equityChart = null;
let tradeHeatmapChart = null;
let monteCarloChart = null;
const equityHistory = [];

function initCharts() {
    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: { color: '#94a3b8', font: { family: "'Inter', sans-serif" } }
            }
        },
        scales: {
            x: {
                ticks: { color: '#64748b' },
                grid: { color: 'rgba(148,163,184,0.06)' }
            },
            y: {
                ticks: { color: '#64748b' },
                grid: { color: 'rgba(148,163,184,0.06)' }
            }
        }
    };

    const priceCtx = document.getElementById('priceChart');
    if (priceCtx) {
        priceChart = new Chart(priceCtx.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Fiyat',
                    data: [],
                    borderColor: '#06b6d4',
                    backgroundColor: 'rgba(6,182,212,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                }]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, ticks: { ...chartDefaults.scales.y.ticks, callback: v => '$' + v.toLocaleString() } } } }
        });
    }

    const equityCtx = document.getElementById('equityChart');
    if (equityCtx) {
        equityChart = new Chart(equityCtx.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Özvarlık',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16,185,129,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                }]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, ticks: { ...chartDefaults.scales.y.ticks, callback: v => '$' + v.toLocaleString() } } } }
        });
    }

    const tradeCtx = document.getElementById('tradeHeatmap');
    if (tradeCtx) {
        tradeHeatmapChart = new Chart(tradeCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'P&L',
                    data: [],
                    backgroundColor: [],
                    borderWidth: 0,
                    borderRadius: 4,
                }]
            },
            options: {
                ...chartDefaults,
                indexAxis: 'y',
                plugins: {
                    ...chartDefaults.plugins,
                    legend: { display: false }
                }
            }
        });
    }

    const mcCtx = document.getElementById('monteCarloChart');
    if (mcCtx) {
        monteCarloChart = new Chart(mcCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Dağılım',
                    data: [],
                    backgroundColor: 'rgba(139,92,246,0.6)',
                    borderColor: '#8b5cf6',
                    borderWidth: 1,
                    borderRadius: 2,
                }]
            },
            options: {
                ...chartDefaults,
                plugins: {
                    ...chartDefaults.plugins,
                    legend: { display: false }
                }
            }
        });
    }
}

function updatePriceChart(trades) {
    if (!priceChart || !trades || trades.length === 0) return;
    const sorted = [...trades].filter(t => t.exit_time).sort((a, b) => new Date(a.exit_time) - new Date(b.exit_time));
    if (sorted.length === 0) return;
    priceChart.data.labels = sorted.map(t => new Date(t.exit_time).toLocaleDateString('tr-TR'));
    priceChart.data.datasets[0].data = sorted.map(t => t.exit_price);
    priceChart.update('none');
}

function updateEquityChart(equity) {
    if (!equityChart) return;
    const now = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    equityHistory.push({ time: now, equity });
    if (equityHistory.length > 100) equityHistory.shift();
    equityChart.data.labels = equityHistory.map(e => e.time);
    equityChart.data.datasets[0].data = equityHistory.map(e => e.equity);
    equityChart.update('none');
}

function updateTradeHeatmap(trades) {
    if (!tradeHeatmapChart || !trades || trades.length === 0) return;
    const recent = trades.slice(-20);
    tradeHeatmapChart.data.labels = recent.map(t => t.symbol || '?');
    tradeHeatmapChart.data.datasets[0].data = recent.map(t => t.pnl || 0);
    tradeHeatmapChart.data.datasets[0].backgroundColor = recent.map(t => (t.pnl || 0) >= 0 ? 'rgba(16,185,129,0.7)' : 'rgba(239,68,68,0.7)');
    tradeHeatmapChart.update('none');
}

function updateMonteCarloChart(data) {
    if (!monteCarloChart || !data || !data.histogram) return;
    const hist = data.histogram;
    monteCarloChart.data.labels = hist.map(h => '$' + h.bin.toLocaleString());
    monteCarloChart.data.datasets[0].data = hist.map(h => h.count);
    monteCarloChart.update('none');
}

// ── Tab Navigation ────────────────────────────────────────
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const target = btn.getAttribute('data-tab');
            if (target) document.getElementById(target)?.classList.add('active');
        });
    });
}

// ── V2 Data Fetchers ──────────────────────────────────────
async function loadRLStatus() {
    try {
        const res = await apiFetch('/api/rl_status');
        if (!res.ok) return;
        const data = await res.json();
        const conf = data.confidence || 0;
        const confEl = document.getElementById('rlConfidenceValue');
        if (confEl) confEl.textContent = conf.toFixed(2);
        const versionEl = document.getElementById('rlModelVersion');
        if (versionEl) versionEl.textContent = data.model_version || '—';
        const episodesEl = document.getElementById('rlEpisodes');
        if (episodesEl) episodesEl.textContent = data.total_episodes || '—';
        const trainedEl = document.getElementById('rlLastTrained');
        if (trainedEl) trainedEl.textContent = data.last_trained ? new Date(data.last_trained).toLocaleDateString('tr-TR') : '—';
        const badgeEl = document.getElementById('rlStatusBadge');
        if (badgeEl) {
            badgeEl.textContent = data.model_loaded ? 'AKTİF' : 'PASİF';
            badgeEl.className = 'rl-status-badge ' + (data.model_loaded ? 'active' : 'inactive');
        }
        const arc = document.getElementById('rlGaugeArc');
        if (arc) {
            const dashLen = Math.max(0, Math.min(1, conf)) * 251.2;
            arc.setAttribute('stroke-dasharray', dashLen + ' 251.2');
            const color = conf > 0.7 ? 'var(--accent-green)' : conf > 0.4 ? 'var(--accent-amber)' : 'var(--accent-red)';
            arc.setAttribute('stroke', color);
            if (confEl) confEl.style.color = color;
        }
    } catch (e) {
        console.log('RL status yüklenemedi');
    }
}

async function loadDriftHeatmap() {
    try {
        const res = await apiFetch('/api/drift_heatmap');
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('driftHeatmap');
        if (!container) return;
        const heatmap = data.heatmap || {};
        const symbols = Object.keys(heatmap);
        if (symbols.length === 0) {
            container.innerHTML = '<div class="empty-state">Drift verisi bulunamadı</div>';
            return;
        }
        const allDays = new Set();
        symbols.forEach(s => Object.keys(heatmap[s]).forEach(d => allDays.add(d)));
        const sortedDays = [...allDays].sort();
        let html = '<div class="heatmap-grid"><div class="heatmap-header-cell"></div>';
        sortedDays.forEach(d => {
            html += `<div class="heatmap-header-cell">${d.slice(5)}</div>`;
        });
        symbols.forEach(symbol => {
            html += `<div class="heatmap-label">${symbol}</div>`;
            sortedDays.forEach(day => {
                const val = heatmap[symbol]?.[day];
                const color = val !== undefined ? getHeatmapColor(val) : 'var(--bg-secondary)';
                const display = val !== undefined ? (val * 100).toFixed(0) + '%' : '—';
                html += `<div class="heatmap-cell" style="background:${color}" title="${symbol} ${day}: ${display}">${display}</div>`;
            });
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        console.log('Drift heatmap yüklenemedi');
    }
}

function getHeatmapColor(val) {
    if (val >= 0.7) return 'rgba(16,185,129,0.8)';
    if (val >= 0.6) return 'rgba(16,185,129,0.5)';
    if (val >= 0.5) return 'rgba(245,158,11,0.6)';
    if (val >= 0.4) return 'rgba(245,158,11,0.8)';
    return 'rgba(239,68,68,0.7)';
}

async function loadDriftSummary() {
    try {
        const res = await apiFetch('/api/drift_summary');
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('driftSummaryContent');
        if (!container) return;
        const perSymbol = data.per_symbol || {};
        const symbols = Object.keys(perSymbol);
        if (symbols.length === 0) {
            container.innerHTML = '<div class="empty-state">Drift verisi bulunamadı</div>';
            return;
        }
        let html = '<div class="drift-summary-bars">';
        symbols.forEach(sym => {
            const info = perSymbol[sym];
            const acc = info.accuracy || 0;
            const drift = info.significant_drift;
            const worsening = info.worsening;
            const accColor = acc > 0.6 ? 'var(--accent-green)' : acc > 0.5 ? 'var(--accent-amber)' : 'var(--accent-red)';
            html += `
                <div class="drift-bar">
                    <div class="drift-bar-header">
                        <span class="drift-symbol">${sym}</span>
                        <span class="drift-accuracy" style="color:${accColor}">${(acc * 100).toFixed(1)}%</span>
                    </div>
                    <div class="drift-bar-track">
                        <div class="drift-bar-fill" style="width:${acc * 100}%;background:${accColor}"></div>
                    </div>
                    <div class="drift-bar-badges">
                        ${drift ? '<span class="drift-badge drift-warn">DRİFT</span>' : ''}
                        ${worsening ? '<span class="drift-badge drift-worse">KÖTÜLEŞİYOR</span>' : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        console.log('Drift summary yüklenemedi');
    }
}

async function loadMonteCarlo() {
    try {
        const res = await apiFetch('/api/monte_carlo');
        if (!res.ok) return;
        const data = await res.json();
        const el = id => document.getElementById(id);
        if (el('mcSimCount')) el('mcSimCount').textContent = data.simulations;
        if (el('mcMean')) el('mcMean').textContent = formatCurrency(data.mean_final);
        if (el('mcProbProfit')) el('mcProbProfit').textContent = ((data.probability_profit || 0) * 100).toFixed(1) + '%';
        if (el('mcMin')) {
            el('mcMin').textContent = formatCurrency(data.min_final);
            el('mcMin').style.color = 'var(--accent-red)';
        }
        if (el('mcMax')) {
            el('mcMax').textContent = formatCurrency(data.max_final);
            el('mcMax').style.color = 'var(--accent-green)';
        }
        updateMonteCarloChart(data);
        const percEl = el('mcPercentiles');
        if (percEl && data.percentiles) {
            const p = data.percentiles;
            percEl.innerHTML = `
                <div class="mc-percentile-row">
                    <span>P5: ${formatCurrency(p.p5)}</span>
                    <span>P25: ${formatCurrency(p.p25)}</span>
                    <span>P50: ${formatCurrency(p.p50)}</span>
                    <span>P75: ${formatCurrency(p.p75)}</span>
                    <span>P95: ${formatCurrency(p.p95)}</span>
                </div>
            `;
        }
    } catch (e) {
        console.log('Monte Carlo yüklenemedi');
    }
}

async function loadRAGQueries() {
    try {
        const res = await apiFetch('/api/rag_queries');
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('ragQueriesList');
        if (!container) return;
        const queries = data.queries || [];
        if (queries.length === 0) {
            container.innerHTML = '<div class="empty-state">RAG sorgusu bulunamadı</div>';
            return;
        }
        let html = '';
        queries.slice(0, 30).forEach(q => {
            const accColor = q.accuracy > 0.6 ? 'var(--accent-green)' : q.accuracy > 0.4 ? 'var(--accent-amber)' : 'var(--accent-red)';
            html += `
                <div class="rag-query-item">
                    <div class="rag-query-header">
                        <span class="rag-query-symbol">${q.symbol}</span>
                        <span class="rag-query-action">${q.action}</span>
                        <span class="rag-query-accuracy" style="color:${accColor}">${(q.accuracy * 100).toFixed(0)}%</span>
                    </div>
                    <div class="rag-query-meta">
                        <span>Rejim: ${q.market_regime}</span>
                        <span>${q.timestamp ? new Date(q.timestamp).toLocaleString('tr-TR') : '—'}</span>
                    </div>
                    ${q.tags && q.tags.length ? `<div class="rag-query-tags">${q.tags.filter(t=>t).map(t => `<span class="rag-tag">${t}</span>`).join('')}</div>` : ''}
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (e) {
        console.log('RAG sorguları yüklenemedi');
    }
}

async function loadRetrospective() {
    try {
        const res = await apiFetch('/api/retrospective');
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('retroList');
        if (!container) return;
        const retros = data.retrospectives || [];
        if (retros.length === 0) {
            container.innerHTML = '<div class="empty-state">Retrospektif analiz bulunamadı</div>';
            return;
        }
        let html = '';
        retros.slice(0, 20).forEach(r => {
            html += `
                <div class="retro-item">
                    <div class="retro-header">
                        <span class="retro-symbol">${r.symbol}</span>
                        <span class="retro-cause">${r.root_cause}</span>
                        <span class="retro-accuracy">${(r.accuracy * 100).toFixed(0)}%</span>
                    </div>
                    <div class="retro-lesson">${escapeHtml(r.lesson)}</div>
                    <div class="retro-meta">
                        <span>Rejim: ${r.market_regime}</span>
                        <span>Giriş: ${r.entry_quality}</span>
                        <span>Çıkış: ${r.exit_quality}</span>
                        <span>${r.timestamp ? new Date(r.timestamp).toLocaleString('tr-TR') : '—'}</span>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (e) {
        console.log('Retrospektif yüklenemedi');
    }
}

// ── Initialize ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initCharts();
    loadLatestAnalysis();
    loadRLStatus();
    loadDriftHeatmap();
    loadDriftSummary();
    loadMonteCarlo();
    loadRAGQueries();
    loadRetrospective();
    setInterval(loadLatestAnalysis, 5000);
    setInterval(() => {
        loadRLStatus();
        loadDriftHeatmap();
        loadDriftSummary();
        loadMonteCarlo();
        loadRAGQueries();
        loadRetrospective();
    }, 15000);
});
