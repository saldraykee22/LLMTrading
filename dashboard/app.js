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
        // data/exports dizininden en son analiz dosyasını yüklemeye çalış
        // Statik dashboard için demo verisi kullanılıyor
        updateDashboard(getDemoData());
    } catch (e) {
        console.log('Veri yüklenemedi, demo verisi kullanılıyor');
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
    const value = document.getElementById('gaugeValue');
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
});
