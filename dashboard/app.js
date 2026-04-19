let equityChart = null;
let currentConfig = {};
const API_KEY = ""; // Skip if not set in server or update if required

// --- Core Helper Functions ---
const switchTab = (tabName) => {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.nav-links a').forEach(link => link.classList.remove('active'));
    
    const activeTab = document.getElementById(`tab-${tabName}`);
    if (activeTab) activeTab.classList.add('active');
    
    document.querySelectorAll('.nav-links a').forEach(link => {
        if (link.innerText.toLowerCase().includes(tabName)) link.classList.add('active');
    });

    const titleMap = {
        'dashboard': 'Command Center',
        'analysis': 'Intelligence Radar',
        'settings': 'Core Configuration',
        'logs': 'Telemetry Stream'
    };
    const titleEl = document.getElementById('current-tab-title');
    if (titleEl && titleMap[tabName]) {
        titleEl.innerText = titleMap[tabName];
    }
};

const fetchAPI = async (endpoint, options = {}) => {
    try {
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        if (API_KEY) headers['X-API-Key'] = API_KEY;

        const response = await fetch(endpoint, { ...options, headers });
        if (response.status === 401) return { error: "unauthorized" };
        return await response.json();
    } catch (err) {
        console.error(`Fetch error ${endpoint}:`, err);
        return { error: true };
    }
};

// Clock Update
setInterval(() => {
    const clock = document.getElementById('clockDisplay');
    if (clock) {
        const now = new Date();
        clock.innerText = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    }
}, 1000);

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    updateDashboard();
    updateAnalysis();
    loadConfig();
    startLogStream();
    
    setInterval(updateDashboard, 5000);
    setInterval(updateAnalysis, 10000);
    
    document.getElementById('startBtn').addEventListener('click', () => controlBot('start'));
    document.getElementById('stopBtn').addEventListener('click', () => controlBot('stop'));
    document.getElementById('saveConfigBtn').addEventListener('click', saveConfig);
});

// --- Chart Logic ---
function initChart() {
    const canvas = document.getElementById('equityChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // Create Premium Gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.15)');
    gradient.addColorStop(0.5, 'rgba(139, 92, 246, 0.05)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Equity Trace',
                data: [],
                borderColor: '#3b82f6',
                borderWidth: 3,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#3b82f6',
                pointHoverBorderWidth: 3,
                fill: true,
                backgroundColor: gradient,
                tension: 0.4,
                shadowBlur: 15,
                shadowColor: 'rgba(59, 130, 246, 0.4)'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(10, 11, 20, 0.9)',
                    titleFont: { family: "'Outfit', sans-serif", weight: 'bold' },
                    bodyFont: { family: "'JetBrains Mono', monospace" }
                }
            },
            scales: {
                x: { display: false },
                y: {
                    grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                    ticks: { 
                        color: '#64748b', 
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: (val) => '$' + val.toLocaleString()
                    }
                }
            }
        }
    });
}

// --- Data Updating ---
async function updateDashboard() {
    const status = await fetchAPI('/api/status');
    
    if (status && !status.error) {
        const equity = status.equity || 10000;
        const totalPnl = status.total_pnl || 0;
        
        document.getElementById('equityValue').innerText = `$${equity.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        document.getElementById('cashValue').innerText = `$${(equity - totalPnl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        document.getElementById('drawdownValue').innerText = `0.00%`; 
        
        const change = ((equity - 10000) / 10000 * 100);
        const changeEl = document.getElementById('equityChangeText');
        changeEl.innerHTML = `
            <span class="trend-value ${change >= 0 ? 'positive' : 'negative'}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span>
            <span class="trend-label">vs initial</span>
        `;

        if (equityChart) {
            const now = new Date().toLocaleTimeString();
            equityChart.data.labels.push(now);
            equityChart.data.datasets[0].data.push(equity);
            if (equityChart.data.labels.length > 50) {
                equityChart.data.labels.shift();
                equityChart.data.datasets[0].data.shift();
            }
            equityChart.update('none');
        }

        const text = document.querySelector('#botStatus');
        if (status.portfolio_loaded) {
            text.innerHTML = '<span class="status-indicator online"></span> Active';
        } else {
            text.innerHTML = '<span class="status-indicator offline"></span> Stopped';
        }
    }
}

async function updateAnalysis() {
    const data = await fetchAPI('/api/analysis');
    if (data && !data.error) {
        if (data.debate_result) {
            document.getElementById('consensusVal').innerText = data.debate_result.consensus_score.toFixed(2);
            document.getElementById('consensusLabel').innerText = `WINNER: ${data.debate_result.winner.toUpperCase()}`;
            document.getElementById('consensusLabel').className = `trend-value ${data.debate_result.winner === 'bull' ? 'text-success' : 'text-danger'}`;
        }

        const feed = document.getElementById('debateFeed');
        if (data.debate_result && data.debate_result.key_arguments) {
            let html = '';
            if (data.debate_result.hallucinations_detected?.length > 0) {
                html += `<div class="hallucination-warning"><i class="ri-error-warning-line"></i> AI Hallucinations Detected in Consensus!</div>`;
            }
            
            data.debate_result.key_arguments.bull.slice(0, 2).forEach(arg => {
                html += `
                <div class="feed-item">
                    <div class="feed-item-header">
                        <span class="feed-tag bull">Bullish</span>
                    </div>
                    <div class="feed-content">${arg}</div>
                </div>`;
            });
            data.debate_result.key_arguments.bear.slice(0, 2).forEach(arg => {
                html += `
                <div class="feed-item">
                    <div class="feed-item-header">
                        <span class="feed-tag bear">Bearish</span>
                    </div>
                    <div class="feed-content">${arg}</div>
                </div>`;
            });
            feed.innerHTML = html || `<div class="feed-empty"><i class="ri-check-line"></i><p>No new analysis data available.</p></div>`;
            
            const detailedFeed = document.getElementById('detailedAnalysisFeed');
            if (detailedFeed) detailedFeed.innerHTML = html;
        }
    }
}

async function controlBot(action) {
    const res = await fetchAPI(`/api/bot/${action}`, { method: 'POST' });
    if (res.status === 'success' || res.success) updateDashboard();
}

async function loadConfig() {
    const data = await fetchAPI('/api/config');
    if (data && !data.error) {
        currentConfig = data;
        if (data.symbols) document.getElementById('cfgSymbols').value = data.symbols.join(', ');
        if (data.risk?.max_open_positions !== undefined) document.getElementById('cfgMaxPos').value = data.risk.max_open_positions;
        if (data.execution?.default_execution_size_pct !== undefined) document.getElementById('cfgBaseSize').value = data.execution.default_execution_size_pct;
        if (data.risk?.max_position_pct !== undefined) document.getElementById('cfgMaxRisk').value = (data.risk.max_position_pct * 100).toFixed(2);
    }
}

async function saveConfig() {
    if (document.getElementById('cfgSymbols').value) {
        currentConfig.symbols = document.getElementById('cfgSymbols').value.split(',').map(s => s.trim()).filter(s => s);
    }
    if (!currentConfig.risk) currentConfig.risk = {};
    if (!currentConfig.execution) currentConfig.execution = {};
    
    currentConfig.risk.max_open_positions = parseInt(document.getElementById('cfgMaxPos').value, 10);
    currentConfig.execution.default_execution_size_pct = parseFloat(document.getElementById('cfgBaseSize').value);
    currentConfig.risk.max_position_pct = parseFloat(document.getElementById('cfgMaxRisk').value) / 100;

    const res = await fetchAPI('/api/config', { method: 'POST', body: JSON.stringify(currentConfig) });
    if (res.success) {
        // Show temporary success feedback
        const btn = document.getElementById('saveConfigBtn');
        const origText = btn.innerHTML;
        btn.innerHTML = '<i class="ri-check-line"></i> Saved';
        btn.classList.add('btn-success');
        btn.classList.remove('btn-primary');
        setTimeout(() => {
            btn.innerHTML = origText;
            btn.classList.remove('btn-success');
            btn.classList.add('btn-primary');
        }, 2000);
    }
}

// ============================================
// Circuit Breaker Functions
// ============================================
async function fetchCircuitBreaker() {
    try {
        const res = await fetch('/api/circuit_breaker');
        const cb = await res.json();
        
        // Update status badge
        const statusEl = document.getElementById('cbStatus');
        if (cb.halted) {
            statusEl.className = 'badge badge-danger';
            statusEl.textContent = '● DURDURULDU';
            showEmergencyAlert('Circuit Breaker Aktif: ' + cb.halt_reason);
        } else {
            statusEl.className = 'badge badge-success';
            statusEl.textContent = '● Aktif';
        }
        
        // Update counters
        document.getElementById('fallbackCount').textContent = `${cb.consecutive_fallbacks}/5`;
        document.getElementById('llmErrorCount').textContent = `${cb.consecutive_llm_errors}/10`;
        document.getElementById('lossCount').textContent = `${cb.consecutive_losses}/5`;
        
        // Update progress bars
        updateProgressBar('fallbackProgress', cb.consecutive_fallbacks, 5);
        updateProgressBar('llmErrorProgress', cb.consecutive_llm_errors, 10);
        updateProgressBar('lossProgress', cb.consecutive_losses, 5);
        
    } catch (err) {
        console.error('Circuit breaker fetch error:', err);
    }
}

function updateProgressBar(elementId, value, max) {
    const el = document.getElementById(elementId);
    const percentage = Math.min((value / max) * 100, 100);
    el.style.width = percentage + '%';
    
    el.classList.remove('warning', 'danger');
    if (value >= max * 0.8) el.classList.add('danger');
    else if (value >= max * 0.5) el.classList.add('warning');
}

async function resetCircuitBreaker() {
    if (!confirm('Tüm circuit breaker sayaçları sıfırlansın mı?')) return;
    
    try {
        const res = await fetch('/api/circuit_breaker/reset', { method: 'POST' });
        const result = await res.json();
        if (result.status === 'success') {
            showToast('Circuit breaker sıfırlandı', 'success');
            fetchCircuitBreaker();
        } else {
            showToast('Sıfırlama başarısız', 'error');
        }
    } catch (err) {
        console.error('Circuit breaker reset error:', err);
        showToast('Sıfırlama hatası: ' + err.message, 'error');
    }
}

// ============================================
// Fallback Audit Functions
// ============================================
async function fetchFallbacks() {
    try {
        const res = await fetch('/api/fallbacks?limit=20');
        const data = await res.json();
        
        // Update summary
        const summaryEl = document.getElementById('fallbackSummary');
        summaryEl.textContent = `Son 24s: ${data.summary.total_fallbacks} fallback`;
        
        // Render table
        const tbody = document.getElementById('fallbackTable');
        if (data.fallbacks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Kayıt bulunamadı</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.fallbacks.map(fb => {
            const time = new Date(fb.timestamp).toLocaleTimeString('tr-TR');
            const reasonClass = fb.reason.toLowerCase().includes('error') ? 'critical' : 'warning';
            return `
                <tr class="${reasonClass}">
                    <td>${time}</td>
                    <td><span class="agent-badge">${fb.agent}</span></td>
                    <td>${truncate(fb.reason, 40)}</td>
                    <td>${fb.symbol || '-'}</td>
                    <td>
                        <button class="btn btn-sm btn-ghost" onclick='showFallbackDetails(${JSON.stringify(fb).replace(/'/g, "\\'")})' title="Detay">
                            <i class="ri-eye-line"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
        
    } catch (err) {
        console.error('Fallback fetch error:', err);
    }
}

function showFallbackDetails(fb) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3>Fallback Detay</h3>
                <button class="btn btn-ghost btn-icon" onclick="this.closest('.modal-overlay').remove()">
                    <i class="ri-close-line"></i>
                </button>
            </div>
            <div class="modal-body">
                <p><strong>Ajan:</strong> ${fb.agent}</p>
                <p><strong>Zaman:</strong> ${new Date(fb.timestamp).toLocaleString('tr-TR')}</p>
                <p><strong>Neden:</strong> ${fb.reason}</p>
                <p><strong>Sembol:</strong> ${fb.symbol || '-'}</p>
                <p><strong>Fallback Değeri:</strong></p>
                <pre>${JSON.stringify(fb.fallback_value, null, 2)}</pre>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

function truncate(str, len) {
    if (!str) return '-';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

// ============================================
// Multi-Account Functions
// ============================================
async function fetchAccounts() {
    try {
        const res = await fetch('/api/accounts');
        const data = await res.json();
        
        if (data.mode === 'multi') {
            // Show account selector
            const selector = document.getElementById('accountSelector');
            const select = document.getElementById('accountSelect');
            selector.style.display = 'block';
            
            // Populate options
            select.innerHTML = '<option value="all">★ Tüm Hesaplar (Kombin)</option>' +
                data.accounts.map(acc => 
                    `<option value="${acc.name}">${acc.name} - $${acc.equity.toLocaleString()}</option>`
                ).join('');
            
            // Store combined data
            window.combinedAccountData = data.combined;
            
        } else {
            document.getElementById('accountSelector').style.display = 'none';
        }
        
    } catch (err) {
        console.error('Accounts fetch error:', err);
    }
}

function switchAccount(accountName) {
    if (accountName === 'all') {
        // Show combined view
        updateDashboardWithAccount(window.combinedAccountData);
    } else {
        // Fetch specific account data
        fetch(`/api/accounts/${accountName}`).then(res => res.json()).then(data => {
            updateDashboardWithAccount(data);
        });
    }
}

function updateDashboardWithAccount(data) {
    // Update equity, cash, positions etc.
    if (data.equity || data.total_equity) {
        document.getElementById('equityValue').textContent = '$' + (data.equity || data.total_equity || 0).toLocaleString();
    }
    if (data.cash || data.total_cash) {
        document.getElementById('cashValue').textContent = '$' + (data.cash || data.total_cash || 0).toLocaleString();
    }
}

// ============================================
// Theme Toggle Functions
// ============================================
function initTheme() {
    const saved = localStorage.theme || 'dark';
    if (saved === 'light') {
        document.documentElement.classList.add('light');
        document.getElementById('themeIcon').className = 'ri-sun-line';
    } else {
        document.getElementById('themeIcon').className = 'ri-moon-line';
    }
}

function toggleTheme() {
    const isLight = document.documentElement.classList.toggle('light');
    localStorage.theme = isLight ? 'light' : 'dark';
    document.getElementById('themeIcon').className = isLight ? 'ri-sun-line' : 'ri-moon-line';
}

// ============================================
// Toast Notifications
// ============================================
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('toast-hide');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function showEmergencyAlert(message) {
    showToast(message, 'error');
}

// ============================================
// Polling Intervals (Optimized)
// ============================================
const POLLING_INTERVALS = {
    portfolio: 10000,        // 10 saniye
    positions: 15000,        // 15 saniye
    circuit_breaker: 5000,   // 5 saniye (güvenlik kritik)
    fallbacks: 30000,        // 30 saniye
    accounts: 20000,         // 20 saniye
    equity_chart: 60000,     // 1 dakika
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    fetchCircuitBreaker();
    fetchFallbacks();
    fetchAccounts();
    
    setInterval(fetchCircuitBreaker, POLLING_INTERVALS.circuit_breaker);
    setInterval(fetchFallbacks, POLLING_INTERVALS.fallbacks);
    setInterval(fetchAccounts, POLLING_INTERVALS.accounts);
});

function startLogStream() {
    const logWindow = document.getElementById('logWindow');
    if (!logWindow) return;
    
    const source = new EventSource('/api/logs/stream');
    source.onmessage = (event) => {
        const line = document.createElement('div');
        let type = event.data.includes('ERROR') ? 'error' : (event.data.includes('WARNING') ? 'warning' : 'info');
        line.className = `log-line log-${type}`;
        line.innerText = event.data;
        logWindow.appendChild(line);
        logWindow.scrollTop = logWindow.scrollHeight;
        if (logWindow.childNodes.length > 500) logWindow.removeChild(logWindow.firstChild);
    };
    source.onerror = () => source.close();
}