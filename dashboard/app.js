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
    trades: [],
    logs: [],
};

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
        const [portfolioRes, statusRes, tradesRes, allocRes] = await Promise.all([
            fetch('/api/portfolio'),
            fetch('/api/status'),
            fetch('/api/trades?limit=10'),
            fetch('/api/portfolio_allocation'),
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

// ── Initialize ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadLatestAnalysis();
    setInterval(loadLatestAnalysis, 5000); // 5 saniyede bir güncelle
});
