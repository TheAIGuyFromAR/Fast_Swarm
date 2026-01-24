/**
 * CoinSwarm Command Center - Main Application
 * Cyberpunk Dashboard for Fast_Swarm
 * Note: innerHTML usage is safe here as all data comes from our own FastAPI backend
 */

// Use same origin as the dashboard (works on any port)
const API_URL = window.location.origin;
const REFRESH_INTERVAL = 60000; // 60 seconds for full refresh (SSE handles real-time)
const CACHE_TTL = 30000; // 30 second cache TTL

// State
let currentPage = 'orchestrator';
let agentsData = [];
let patternsData = [];
let tradesData = [];
let currentSort = { agents: 'fitness_score', patterns: 'fitness_score' };
let killRateHistory = [];
let eventSource = null;

// ============================================
// CACHING LAYER
// ============================================

const cache = new Map();

async function fetchWithCache(url, maxAgeMs = CACHE_TTL) {
    const cacheKey = url;
    const cached = cache.get(cacheKey);

    if (cached && (Date.now() - cached.timestamp < maxAgeMs)) {
        return cached.data;
    }

    try {
        const response = await fetch(API_URL + url);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();

        cache.set(cacheKey, { data, timestamp: Date.now() });
        return data;
    } catch (error) {
        // Return stale cache if available on error
        if (cached) {
            console.warn('Using stale cache for', url, ':', error.message);
            return cached.data;
        }
        throw error;
    }
}

function invalidateCache(urlPattern) {
    for (const key of cache.keys()) {
        if (key.includes(urlPattern)) {
            cache.delete(key);
        }
    }
}

// ============================================
// SERVER-SENT EVENTS (Real-time updates)
// ============================================

function initSSE() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(API_URL + '/system/events');

    eventSource.onmessage = function(event) {
        try {
            const message = JSON.parse(event.data);

            switch (message.type) {
                case 'orchestrator':
                    // Update orchestrator HUD in real-time
                    if (currentPage === 'orchestrator') {
                        updatePhaseHUD(message.data);
                        updateOrchestratorMetrics(message.data);
                    }
                    break;

                case 'streams':
                    // Update stream status indicator
                    updateStreamStatus(message.data);
                    break;

                case 'error':
                    console.warn('SSE error:', message.data);
                    break;
            }
        } catch (e) {
            console.error('SSE parse error:', e);
        }
    };

    eventSource.onerror = function(event) {
        console.warn('SSE connection error, will reconnect...');
        // EventSource automatically reconnects
    };

    addLogEntry('SYSTEM', 'Real-time updates connected');
}

function updateOrchestratorMetrics(data) {
    // Update progress bars and counts from SSE data
    if (data.patterns_total > 0) {
        var pct = Math.round((data.patterns_tested / data.patterns_total) * 100);
        updateBar('patterns-bar', pct);
    }
    if (data.agents_total > 0) {
        var pct = Math.round((data.agents_tested / data.agents_total) * 100);
        updateBar('agents-bar', pct);
    }
}

function updateStreamStatus(streams) {
    var statusIndicator = document.getElementById('system-status');
    if (!statusIndicator) return;

    var allConnected = Object.values(streams).every(function(s) {
        return s.state === 'connected';
    });

    statusIndicator.classList.toggle('offline', !allConnected);
    statusIndicator.querySelector('.status-text').textContent = allConnected ? 'ONLINE' : 'DEGRADED';
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initControls();
    initClock();
    initSSE();  // Start real-time updates
    startDataRefresh();
    addLogEntry('SYSTEM', 'Dashboard initialized');
});

// ============================================
// NAVIGATION
// ============================================

function initNavigation() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const page = btn.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.page === page);
    });

    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === 'page-' + page);
    });

    currentPage = page;

    // Start/stop position auto-refresh based on active page
    if (page === 'trading') {
        startPositionRefresh();
    } else {
        stopPositionRefresh();
    }

    switch(page) {
        case 'orchestrator': fetchOrchestratorData(); break;
        case 'market': fetchMarketData(); break;
        case 'patterns': fetchPatternsData(); break;
        case 'agents': fetchAgentsData(); break;
        case 'trades': fetchTradesData(); break;
        case 'trading': loadTradingData(); break;
        case 'taskmaster': loadTaskmasterData(); break;
    }
}

// ============================================
// CONTROLS & BUTTONS
// ============================================

function initControls() {
    var btnEvolution = document.getElementById('btn-evolution');
    var btnSpawn = document.getElementById('btn-spawn');
    var btnBacktest = document.getElementById('btn-backtest');
    var btnCull = document.getElementById('btn-cull');
    var btnChaos = document.getElementById('btn-chaos');
    var btnTests = document.getElementById('btn-tests');

    if (btnEvolution) btnEvolution.addEventListener('click', function() { triggerAction('/evolution/start', 'POST', 'Evolution started'); });
    if (btnSpawn) btnSpawn.addEventListener('click', spawnAgentsWithPrompt);
    if (btnBacktest) btnBacktest.addEventListener('click', triggerBacktestWithProgress);
    if (btnCull) btnCull.addEventListener('click', cullWithPreview);
    if (btnChaos) btnChaos.addEventListener('click', function() { triggerAction('/system/robustness/trigger_chaos', 'POST', 'Chaos triggered'); });
    if (btnTests) btnTests.addEventListener('click', function() { triggerAction('/tests/run/all', 'POST', 'Tests started'); });

    var slider = document.getElementById('parallelism-slider');
    var sliderValue = document.getElementById('parallelism-value');
    if (slider && sliderValue) {
        slider.addEventListener('input', function() {
            sliderValue.textContent = slider.value;
        });
    }

    document.querySelectorAll('#page-patterns .sort-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('#page-patterns .sort-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentSort.patterns = btn.dataset.sort;
            renderPatternsTable();
        });
    });

    document.querySelectorAll('#page-agents .sort-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('#page-agents .sort-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentSort.agents = btn.dataset.sort;
            renderAgentsTable();
        });
    });
}

async function triggerAction(endpoint, method, successMsg) {
    try {
        addLogEntry('ACTION', 'Triggering ' + endpoint + '...');
        var response = await fetch(API_URL + endpoint, { method: method });
        if (response.ok) {
            addLogEntry('SUCCESS', successMsg);
        } else {
            var error = await response.text();
            addLogEntry('ERROR', 'Failed: ' + error);
        }
    } catch (error) {
        addLogEntry('ERROR', 'Request failed: ' + error.message);
    }
}

// Spawn agents with count prompt
async function spawnAgentsWithPrompt() {
    var count = prompt('How many agents to spawn?', '10');
    if (!count) return;
    var countNum = parseInt(count, 10);
    if (isNaN(countNum) || countNum < 1) {
        addLogEntry('ERROR', 'Invalid count');
        return;
    }
    addLogEntry('ACTION', 'Spawning ' + countNum + ' agents...');
    try {
        var response = await fetch(API_URL + '/actions/spawn?count=' + countNum, { method: 'POST' });
        var data = await response.json();
        if (response.ok) {
            addLogEntry('SUCCESS', 'Spawned ' + (data.agents ? data.agents.length : countNum) + ' agents (AI: ' + (data.ai_selection ? 'Yes' : 'No') + ')');
            fetchOrchestratorData();
        } else {
            addLogEntry('ERROR', 'Spawn failed: ' + (data.detail || 'Unknown error'));
        }
    } catch (error) {
        addLogEntry('ERROR', 'Spawn request failed: ' + error.message);
    }
}

// Cull with dry_run preview first
async function cullWithPreview() {
    addLogEntry('ACTION', 'Analyzing agents for cull (dry run)...');
    try {
        var response = await fetch(API_URL + '/actions/cull?dry_run=true&survival_rate=0.6', { method: 'POST' });
        var data = await response.json();
        if (!response.ok) {
            addLogEntry('ERROR', 'Cull preview failed');
            return;
        }
        var msg = 'Would cull ' + data.would_cull + ' agents, keeping ' + data.would_survive;
        if (data.bottom_agents && data.bottom_agents.length > 0) {
            msg += '\nBottom agents: ' + data.bottom_agents.slice(0, 5).map(function(a) {
                return (a.name || 'Unknown') + ' (fitness: ' + (a.fitness || 0).toFixed(1) + ')';
            }).join(', ');
        }
        addLogEntry('INFO', msg);
        if (data.would_cull === 0) {
            addLogEntry('INFO', 'No agents to cull');
            return;
        }
        var confirmed = confirm('Cull ' + data.would_cull + ' weak agents?\n\n' + msg);
        if (!confirmed) {
            addLogEntry('INFO', 'Cull cancelled');
            return;
        }
        addLogEntry('ACTION', 'Executing cull...');
        var cullResponse = await fetch(API_URL + '/actions/cull?survival_rate=0.6', { method: 'POST' });
        var cullData = await cullResponse.json();
        if (cullResponse.ok) {
            addLogEntry('SUCCESS', 'Culled ' + (cullData.culled || data.would_cull) + ' agents');
            fetchOrchestratorData();
        } else {
            addLogEntry('ERROR', 'Cull failed: ' + (cullData.detail || 'Unknown error'));
        }
    } catch (error) {
        addLogEntry('ERROR', 'Cull request failed: ' + error.message);
    }
}

// Backtest with limit and progress polling
var backtestPollInterval = null;

async function triggerBacktestWithProgress() {
    var limitStr = prompt('Limit number of agents to backtest? (leave empty for all)', '');
    var limit = limitStr ? parseInt(limitStr, 10) : null;
    if (limitStr && (isNaN(limit) || limit < 1)) {
        addLogEntry('ERROR', 'Invalid limit');
        return;
    }
    var url = '/actions/backtest';
    if (limit) url += '?limit=' + limit;
    addLogEntry('ACTION', 'Starting backtest' + (limit ? ' (limit: ' + limit + ')' : '') + '...');
    try {
        var response = await fetch(API_URL + url, { method: 'POST' });
        var data = await response.json();
        if (response.ok) {
            addLogEntry('INFO', 'Backtest started in background');
            if (backtestPollInterval) clearInterval(backtestPollInterval);
            backtestPollInterval = setInterval(pollBacktestStatus, 2000);
        } else {
            addLogEntry('ERROR', 'Backtest failed: ' + (data.detail || 'Unknown error'));
        }
    } catch (error) {
        addLogEntry('ERROR', 'Backtest request failed: ' + error.message);
    }
}

async function pollBacktestStatus() {
    try {
        var response = await fetch(API_URL + '/actions/backtest/status');
        var data = await response.json();
        var pct = data.total > 0 ? Math.round((data.progress / data.total) * 100) : 0;
        if (data.running) {
            addLogEntry('INFO', 'Backtest progress: ' + pct + '% (' + data.progress + '/' + data.total + ') - ' + (data.current_agent || '...'));
        } else {
            clearInterval(backtestPollInterval);
            backtestPollInterval = null;
            var completed = data.completed ? data.completed.length : 0;
            var errors = data.errors ? data.errors.length : 0;
            addLogEntry('SUCCESS', 'Backtest complete! ' + completed + ' agents tested' + (errors > 0 ? ', ' + errors + ' errors' : ''));
            fetchOrchestratorData();
        }
    } catch (error) {
        console.error('Backtest poll error:', error);
    }
}

// ============================================
// NOTIFICATION HELPER
// ============================================

function showNotification(message, type) {
    var level = (type === 'error') ? 'ERROR' : (type === 'success') ? 'SUCCESS' : 'INFO';
    addLogEntry(level, message);
}

// ============================================
// PATTERN ACTION FUNCTIONS
// ============================================

async function cullWeakPatterns() {
    if (!confirm('Cull patterns with 100+ tests and low regime fitness?')) return;
    try {
        var res = await fetch(API_URL + '/patterns/cull', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var result = await res.json();
        showNotification('Culled ' + (result.culled_count || 0) + ' weak patterns', 'success');
        fetchPatternsData();
    } catch (err) {
        console.error('[cullWeakPatterns] Error:', err);
        showNotification('Cull failed: ' + err.message, 'error');
    }
}

async function triggerPatternDiscovery() {
    if (!confirm('Start pattern discovery cycle? This may take several minutes.')) return;
    try {
        var res = await fetch(API_URL + '/patterns/discover', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var result = await res.json();
        showNotification('Discovery started: ' + (result.message || 'running'), 'success');
    } catch (err) {
        console.error('[triggerPatternDiscovery] Error:', err);
        showNotification('Discovery failed: ' + err.message, 'error');
    }
}

// ============================================
// AGENT ACTION FUNCTIONS
// ============================================

async function spawnAgents() {
    if (!confirm('Spawn new agents from top patterns?')) return;
    try {
        var res = await fetch(API_URL + '/actions/spawn', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var result = await res.json();
        showNotification('Spawned ' + (result.agents ? result.agents.length : 0) + ' agents', 'success');
        fetchAgentsData();
    } catch (err) {
        console.error('[spawnAgents] Error:', err);
        showNotification('Spawn failed: ' + err.message, 'error');
    }
}

async function cullAgents() {
    if (!confirm('Cull weakest agents by fitness score?')) return;
    try {
        var res = await fetch(API_URL + '/actions/cull', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var result = await res.json();
        showNotification('Culled ' + (result.culled || 0) + ' agents, ' + (result.survived || 0) + ' survived', 'success');
        fetchAgentsData();
    } catch (err) {
        console.error('[cullAgents] Error:', err);
        showNotification('Cull failed: ' + err.message, 'error');
    }
}

async function runEvolution() {
    if (!confirm('Start evolution cycle? This runs in the background.')) return;
    try {
        var res = await fetch(API_URL + '/evolution/start', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var result = await res.json();
        showNotification('Evolution started: ' + (result.message || result.status || 'running'), 'success');
    } catch (err) {
        console.error('[runEvolution] Error:', err);
        showNotification('Evolution failed: ' + err.message, 'error');
    }
}

// ============================================
// CLOCK
// ============================================

function initClock() {
    updateClock();
    setInterval(updateClock, 1000);
}

function updateClock() {
    var now = new Date();
    var timeStr = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('clock').textContent = timeStr;
}

// ============================================
// DATA REFRESH
// ============================================

function startDataRefresh() {
    fetchAllData();
    setInterval(fetchAllData, REFRESH_INTERVAL);
}

async function fetchAllData() {
    try {
        await fetchOrchestratorData();
        switch(currentPage) {
            case 'market': await fetchMarketData(); break;
            case 'patterns': await fetchPatternsData(); break;
            case 'agents': await fetchAgentsData(); break;
            case 'trades': await fetchTradesData(); break;
        }
        updateLastRefresh();
    } catch (error) {
        console.error('Data fetch error:', error);
        addLogEntry('ERROR', 'Data refresh failed: ' + error.message);
    }
}

function updateLastRefresh() {
    var now = new Date();
    document.getElementById('last-update').textContent = 'Last update: ' + now.toLocaleTimeString('en-US', { hour12: false });
}

// ============================================
// ORCHESTRATOR PAGE
// ============================================

async function fetchOrchestratorData() {
    try {
        var results = await Promise.allSettled([
            fetch(API_URL + '/agents/stats/average'),
            fetch(API_URL + '/patterns/stats/average'),
            fetch(API_URL + '/system/health'),
            fetch(API_URL + '/evolution/monitor/current')
        ]);

        if (results[0].status === 'fulfilled' && results[0].value.ok) {
            var stats = await results[0].value.json();
            // API returns: active_count, avg_fitness, average_traits
            var agentCount = stats.active_count || stats.count || 0;
            var avgFitness = stats.avg_fitness || stats.average_fitness || 0;
            updateMetric('metric-agents', agentCount || '--');
            updateMetric('metric-fitness', avgFitness ? avgFitness.toFixed(1) : '--');
            updateMetric('metric-elo', '--'); // Not in stats endpoint
            updateBar('agents-bar', Math.min(agentCount, 100));
            updateBar('fitness-bar', avgFitness);
            updateBar('elo-bar', 50); // Default until we add ELO to stats
        }

        if (results[1].status === 'fulfilled' && results[1].value.ok) {
            var pStats = await results[1].value.json();
            // API returns: count, averages, by_status, top_performers
            var patternCount = pStats.count || 0;
            updateMetric('metric-patterns', patternCount || '--');
            updateBar('patterns-bar', Math.min(patternCount, 100));
        }

        if (results[2].status === 'fulfilled' && results[2].value.ok) {
            var health = await results[2].value.json();
            var statusIndicator = document.getElementById('system-status');
            var isHealthy = health.streams && Object.values(health.streams).every(function(s) { return s.state === 'connected'; });
            if (statusIndicator) {
                statusIndicator.classList.toggle('offline', !isHealthy);
                statusIndicator.querySelector('.status-text').textContent = isHealthy ? 'ONLINE' : 'DEGRADED';
            }
        }

        if (results[3].status === 'fulfilled') {
            if (results[3].value.ok) {
                var cycle = await results[3].value.json();
                updatePhaseHUD(cycle);
            } else {
                // No active cycle - show all phases as idle
                updatePhaseHUD({ phase: null });
            }
        }

        updateKillRateChart();
    } catch (error) {
        console.error('Orchestrator data error:', error);
    }
}

function updateMetric(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

function updateBar(id, percent) {
    var el = document.getElementById(id);
    if (el) el.style.width = Math.min(100, Math.max(0, percent)) + '%';
}

function updatePhaseHUD(cycle) {
    var phases = ['chaos', 'discovery', 'backtest', 'select'];
    var currentPhase = cycle && cycle.phase ? cycle.phase.toLowerCase() : '';

    phases.forEach(function(phase, index) {
        var ring = document.getElementById('phase-' + phase + '-ring');
        var status = document.getElementById('phase-' + phase + '-status');
        var card = ring ? ring.closest('.phase-card') : null;

        if (ring && status && card) {
            var isActive = currentPhase === phase;
            var isComplete = phases.indexOf(currentPhase) > index;
            var progress = isComplete ? 0 : (isActive ? 141.5 : 283);
            ring.style.strokeDashoffset = progress;
            status.textContent = isComplete ? 'COMPLETE' : (isActive ? 'RUNNING' : 'IDLE');
            status.classList.toggle('running', isActive);
            card.classList.toggle('active', isActive);
        }
    });
}

function updateKillRateChart() {
    var canvas = document.getElementById('kill-rate-chart');
    if (!canvas) return;

    var ctx = canvas.getContext('2d');
    var width = canvas.width;
    var height = canvas.height;

    killRateHistory.push(85 + Math.random() * 15);
    if (killRateHistory.length > 50) killRateHistory.shift();

    ctx.fillStyle = '#1a1a25';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = '#2a2a3a';
    ctx.lineWidth = 1;
    for (var i = 0; i <= 4; i++) {
        var y = (height / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    if (killRateHistory.length > 1) {
        ctx.strokeStyle = '#00ffff';
        ctx.lineWidth = 2;
        ctx.shadowColor = '#00ffff';
        ctx.shadowBlur = 10;
        ctx.beginPath();

        killRateHistory.forEach(function(value, index) {
            var x = (width / (killRateHistory.length - 1)) * index;
            var chartY = height - (value / 100) * height;
            if (index === 0) {
                ctx.moveTo(x, chartY);
            } else {
                ctx.lineTo(x, chartY);
            }
        });

        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}

// ============================================
// MARKET PAGE
// ============================================

async function fetchMarketData() {
    try {
        // Fetch latest candles for each asset to get current prices
        // DB stores symbols as BTC, ETH, SOL (no USDT suffix)
        var assets = ['BTC', 'ETH', 'SOL'];
        var results = await Promise.allSettled(
            assets.map(function(asset) {
                return fetch(API_URL + '/market_data/candles?symbol=' + encodeURIComponent(asset) + '&timeframe=1h&limit=2');
            })
        );

        var tickers = [];
        for (var i = 0; i < results.length; i++) {
            if (results[i].status === 'fulfilled' && results[i].value.ok) {
                var candles = await results[i].value.json();
                if (candles && candles.length >= 2) {
                    var current = candles[0];
                    var prev = candles[1];
                    var change = prev.close > 0 ? ((current.close - prev.close) / prev.close) * 100 : 0;
                    tickers.push({
                        symbol: assets[i].split('/')[0],
                        price: current.close,
                        change: change
                    });
                }
            }
        }

        if (tickers.length > 0) {
            updatePriceDisplays(tickers);
        }
    } catch (error) {
        console.error('Market data fetch error:', error);
    }

    // Fetch real sentiment data from API
    try {
        var sentimentRes = await fetch(API_URL + '/sentiment/summary');
        if (sentimentRes.ok) {
            var sentiment = await sentimentRes.json();
            if (sentiment.fear_greed) {
                updateFearGreed(sentiment.fear_greed.value);
            }
            if (sentiment.btc_dominance) {
                updateBtcDominance(sentiment.btc_dominance);
            }
        }
    } catch (error) {
        console.error('Sentiment fetch error:', error);
        updateFearGreed(50); // Neutral fallback
    }

    // Fetch funding rates
    fetchFundingRates();

    // Fetch Bear Protection regime
    fetchRegimeData();
}

// Store prices for ratio calculations
var latestPrices = { BTC: 0, ETH: 0, SOL: 0 };

function updatePriceDisplays(tickers) {
    var mapping = {
        'BTC': { price: 'btc-price', change: 'btc-change' },
        'BTCUSDT': { price: 'btc-price', change: 'btc-change' },
        'ETH': { price: 'eth-price', change: 'eth-change' },
        'ETHUSDT': { price: 'eth-price', change: 'eth-change' },
        'SOL': { price: 'sol-price', change: 'sol-change' },
        'SOLUSDT': { price: 'sol-price', change: 'sol-change' }
    };

    tickers.forEach(function(ticker) {
        var map = mapping[ticker.symbol];
        if (map) {
            var priceEl = document.getElementById(map.price);
            var changeEl = document.getElementById(map.change);

            if (priceEl && ticker.price) {
                priceEl.textContent = '$' + ticker.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                // Store for ratio calculations
                var sym = ticker.symbol.replace('USDT', '');
                if (sym === 'BTC' || sym === 'ETH' || sym === 'SOL') {
                    latestPrices[sym] = ticker.price;
                }
            }
            if (changeEl) {
                var change = ticker.change || 0;
                changeEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(2) + '%';
                changeEl.className = 'price-change ' + (change >= 0 ? 'positive' : 'negative');
            }
        }
    });

    // Calculate and display ratios
    updateRatios();
}

function updateRatios() {
    // BTC/ETH ratio
    if (latestPrices.BTC > 0 && latestPrices.ETH > 0) {
        var btcEthRatio = latestPrices.BTC / latestPrices.ETH;
        var btcEthEl = document.getElementById('btc-eth-ratio');
        if (btcEthEl) {
            btcEthEl.textContent = btcEthRatio.toFixed(2);
        }
    }

    // BTC/SOL ratio
    if (latestPrices.BTC > 0 && latestPrices.SOL > 0) {
        var btcSolRatio = latestPrices.BTC / latestPrices.SOL;
        var btcSolEl = document.getElementById('btc-sol-ratio');
        if (btcSolEl) {
            btcSolEl.textContent = btcSolRatio.toFixed(2);
        }
    }
}

function updateFearGreed(value) {
    var needle = document.getElementById('fear-greed-needle');
    var valueEl = document.getElementById('fear-greed-value');
    var labelEl = document.getElementById('fear-greed-label');

    if (needle) {
        var rotation = (value / 100) * 180 - 90;
        needle.style.transform = 'translateX(-50%) rotate(' + rotation + 'deg)';
    }
    if (valueEl) valueEl.textContent = value;
    if (labelEl) {
        if (value < 25) labelEl.textContent = 'EXTREME FEAR';
        else if (value < 45) labelEl.textContent = 'FEAR';
        else if (value < 55) labelEl.textContent = 'NEUTRAL';
        else if (value < 75) labelEl.textContent = 'GREED';
        else labelEl.textContent = 'EXTREME GREED';
    }
}

function updateBtcDominance(data) {
    var domEl = document.getElementById('btc-dominance-value');
    var capEl = document.getElementById('market-cap-value');

    if (domEl && data.dominance) {
        domEl.textContent = data.dominance.toFixed(1) + '%';
    }
    if (capEl && data.total_market_cap) {
        var cap = data.total_market_cap;
        if (cap >= 1e12) {
            capEl.textContent = '$' + (cap / 1e12).toFixed(2) + 'T';
        } else if (cap >= 1e9) {
            capEl.textContent = '$' + (cap / 1e9).toFixed(0) + 'B';
        } else {
            capEl.textContent = '$' + cap.toLocaleString();
        }
    }
}

async function fetchFundingRates() {
    try {
        var res = await fetch(API_URL + '/sentiment/funding-rates?limit=100');
        if (!res.ok) return;
        var rates = await res.json();

        // Get latest rate per symbol
        var latest = {};
        rates.forEach(function(r) {
            var sym = r.symbol.replace('-USD', '').replace('USDT', '');
            if (!latest[sym]) latest[sym] = r;
        });

        // Update display
        ['BTC', 'ETH', 'SOL'].forEach(function(sym) {
            var el = document.getElementById('funding-' + sym.toLowerCase());
            if (el && latest[sym]) {
                var rate = latest[sym].funding_rate * 100; // Convert to percentage
                var bps = (rate * 100).toFixed(2); // Basis points
                el.textContent = (rate >= 0 ? '+' : '') + bps + ' bps';
                el.className = 'funding-value ' + (rate >= 0 ? 'positive' : 'negative');
            }
        });
    } catch (e) {
        console.error('Funding rates error:', e);
    }
}

async function fetchRegimeData() {
    try {
        var res = await fetch(API_URL + '/market_data/regime');
        if (!res.ok) return;
        var data = await res.json();

        // Get portfolio-weighted regime
        var portfolio = data.portfolio || {};
        var regime = portfolio.effective_regime || 'NEUTRAL';
        var weightedScore = portfolio.weighted_regime_score || 0;

        // Update regime badge
        var badge = document.getElementById('regime-badge');
        if (badge) {
            badge.textContent = regime;
            badge.className = 'regime-badge regime-' + regime.toLowerCase();
        }

        // Update weighted score display (shows -1 to +1 score)
        var trigger = document.getElementById('regime-trigger');
        if (trigger) {
            var scoreDisplay = weightedScore >= 0 ? '+' + weightedScore.toFixed(2) : weightedScore.toFixed(2);
            trigger.textContent = 'Score: ' + scoreDisplay;
        }

        // Update utilization bar
        var util = data.utilization || {};
        var investedPct = util.invested_pct || 0;
        var limitPct = util.limit_pct || portfolio.max_position_pct || 65;

        var fill = document.getElementById('utilization-fill');
        if (fill) {
            fill.style.width = Math.min(investedPct, 100) + '%';
            fill.className = 'utilization-fill' + (util.over_limit ? ' over-limit' : '');
        }

        var limitLine = document.getElementById('utilization-limit');
        if (limitLine) {
            limitLine.style.left = limitPct + '%';
        }

        // Update labels
        var investedLabel = document.getElementById('invested-label');
        if (investedLabel) {
            investedLabel.textContent = investedPct.toFixed(1) + '% invested';
        }

        var limitLabel = document.getElementById('limit-label');
        if (limitLabel) {
            limitLabel.textContent = limitPct + '% limit';
        }

        // Update stats
        var investedEl = document.getElementById('regime-invested');
        if (investedEl) {
            investedEl.textContent = '$' + (util.invested_usd || 0).toLocaleString();
        }

        var headroomEl = document.getElementById('regime-headroom');
        if (headroomEl) {
            headroomEl.textContent = (util.headroom_pct || 0).toFixed(1) + '%';
            headroomEl.className = 'regime-stat-value' + (util.over_limit ? ' negative' : ' positive');
        }

        // Update per-asset count
        var durationEl = document.getElementById('regime-duration');
        if (durationEl) {
            var byAsset = data.by_asset || {};
            var assetCount = Object.keys(byAsset).length;
            durationEl.textContent = assetCount + ' assets';
        }
    } catch (e) {
        console.error('Regime data error:', e);
    }
}

// ============================================
// PATTERNS PAGE
// ============================================

async function fetchPatternsData() {
    try {
        var results = await Promise.allSettled([
            fetch(API_URL + '/patterns?limit=100'),
            fetch(API_URL + '/patterns/stats/average')
        ]);

        // Handle patterns list
        if (results[0].status === 'fulfilled' && results[0].value.ok) {
            patternsData = await results[0].value.json();
            console.log('Patterns loaded:', patternsData.length, 'patterns');
            renderPatternsTable();
        } else {
            var reason = results[0].status === 'rejected' ? results[0].reason : 'HTTP ' + results[0].value.status;
            console.error('Patterns fetch failed:', reason);
            document.getElementById('patterns-table').textContent = 'Error loading patterns: ' + reason;
        }

        // Handle stats separately
        if (results[1].status === 'fulfilled' && results[1].value.ok) {
            var stats = await results[1].value.json();
            // API returns: count, averages {fitness_score, win_rate, total_trades, total_roi_pct}, by_status, top_performers
            var avgs = stats.averages || {};
            document.getElementById('stat-pattern-total').textContent = stats.count || patternsData.length;
            document.getElementById('stat-pattern-fitness').textContent = avgs.fitness_score ? avgs.fitness_score.toFixed(1) : '--';
            document.getElementById('stat-pattern-sharpe').textContent = avgs.sortino_ratio ? avgs.sortino_ratio.toFixed(2) : '--';
            document.getElementById('stat-pattern-roi').textContent = avgs.total_roi_pct ? avgs.total_roi_pct.toFixed(1) + '%' : '--';
        }
    } catch (error) {
        console.error('Patterns fetch error:', error);
        document.getElementById('patterns-table').textContent = 'Error loading patterns: ' + error.message;
    }
}

function renderPatternsTable() {
    var container = document.getElementById('patterns-table');
    if (!container) {
        console.error('patterns-table container not found');
        return;
    }

    console.log('renderPatternsTable called, patternsData.length:', patternsData.length);

    if (patternsData.length === 0) {
        container.textContent = 'No patterns found';
        return;
    }

    try {
        // Separate tested vs untested patterns
        // A pattern is "tested" if it has total_runs > 0 OR last_backtest_at is set
        // Note: fitness_score can be 0 or negative for tested patterns!
        var testedPatterns = patternsData.filter(function(p) {
            var hasRuns = p.total_runs && parseInt(p.total_runs) > 0;
            var hasBacktestDate = p.last_backtest_at && p.last_backtest_at !== null;
            return hasRuns || hasBacktestDate;
        });

        // Patterns that failed to produce any results (broken indicators, etc.)
        var brokenPatterns = patternsData.filter(function(p) {
            var wasTested = (p.total_runs && parseInt(p.total_runs) > 0) || p.last_backtest_at;
            var hasNoTrades = !p.total_trades || parseInt(p.total_trades) === 0;
            return wasTested && hasNoTrades;
        });

        // Untested patterns (never run through backtest)
        var untestedPatterns = patternsData.filter(function(p) {
            var hasRuns = p.total_runs && parseInt(p.total_runs) > 0;
            var hasBacktestDate = p.last_backtest_at && p.last_backtest_at !== null;
            return !hasRuns && !hasBacktestDate;
        });

        console.log('Tested patterns:', testedPatterns.length, 'Broken:', brokenPatterns.length, 'Untested:', untestedPatterns.length);

        if (testedPatterns.length === 0 && untestedPatterns.length > 0) {
            container.textContent = 'No backtested patterns yet (' + untestedPatterns.length + ' patterns pending backtest)';
            return;
        }

        if (testedPatterns.length === 0) {
            container.textContent = 'No patterns found';
            return;
        }

        var sorted = testedPatterns.slice().sort(function(a, b) {
            return (parseFloat(b[currentSort.patterns]) || 0) - (parseFloat(a[currentSort.patterns]) || 0);
        });

        var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    ['RANK', 'PATTERN ID', 'FITNESS', 'ROI %', 'SORTINO', 'WIN RATE', 'MAX DD'].forEach(function(text) {
        var th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    sorted.forEach(function(pattern, index) {
        var rank = index + 1;
        var fitness = parseFloat(pattern.fitness_score) || 0;
        var roiRaw = pattern.total_roi_pct;
        var roi = (roiRaw !== null && roiRaw !== undefined) ? parseFloat(roiRaw) : null;
        // Prefer sortino_ratio; fall back to sharpe_ratio if sortino is null
        var sortinoRaw = pattern.sortino_ratio;
        if (sortinoRaw === null || sortinoRaw === undefined) {
            sortinoRaw = pattern.sharpe_ratio;
        }
        var sortino = (sortinoRaw !== null && sortinoRaw !== undefined) ? parseFloat(sortinoRaw) : null;
        var winRateRaw = pattern.win_rate;
        var winRate = (winRateRaw !== null && winRateRaw !== undefined) ? parseFloat(winRateRaw) * 100 : null;
        var maxDDRaw = pattern.max_drawdown_pct;
        var maxDD = (maxDDRaw !== null && maxDDRaw !== undefined) ? parseFloat(maxDDRaw) : null;

        var tr = document.createElement('tr');
        tr.onclick = function() { toggleDetails('details-' + pattern.pattern_id); };

        var tdRank = document.createElement('td');
        tdRank.className = 'rank' + (rank <= 3 ? ' rank-' + rank : '');
        tdRank.textContent = rank;
        tr.appendChild(tdRank);

        var tdId = document.createElement('td');
        tdId.style.fontFamily = 'var(--font-mono)';
        tdId.style.fontSize = '0.8em';
        tdId.textContent = (pattern.pattern_id || 'N/A').slice(0, 16) + '...';
        tr.appendChild(tdId);

        var tdFitness = document.createElement('td');
        var fitnessSpan = document.createElement('span');
        fitnessSpan.className = 'metric positive';
        fitnessSpan.textContent = fitness.toFixed(1);
        tdFitness.appendChild(fitnessSpan);
        var fitnessBar = document.createElement('div');
        fitnessBar.className = 'fitness-bar';
        var fitnessFill = document.createElement('div');
        fitnessFill.className = 'fitness-fill';
        fitnessFill.style.width = Math.min(fitness, 100) + '%';
        fitnessBar.appendChild(fitnessFill);
        tdFitness.appendChild(fitnessBar);
        tr.appendChild(tdFitness);

        var tdRoi = document.createElement('td');
        tdRoi.className = 'metric ' + (roi !== null ? (roi >= 10 ? 'positive' : roi < 0 ? 'negative' : 'neutral') : 'neutral');
        tdRoi.textContent = roi !== null ? roi.toFixed(1) + '%' : 'N/A';
        tr.appendChild(tdRoi);

        var tdSortino = document.createElement('td');
        tdSortino.className = 'metric ' + (sortino !== null ? (sortino >= 1.5 ? 'positive' : sortino < 0.5 ? 'negative' : 'neutral') : 'neutral');
        tdSortino.textContent = sortino !== null ? sortino.toFixed(2) : 'N/A';
        tr.appendChild(tdSortino);

        var tdWr = document.createElement('td');
        tdWr.className = 'metric ' + (winRate !== null ? (winRate >= 55 ? 'positive' : winRate < 45 ? 'negative' : 'neutral') : 'neutral');
        tdWr.textContent = winRate !== null ? winRate.toFixed(1) + '%' : 'N/A';
        tr.appendChild(tdWr);

        var tdDD = document.createElement('td');
        tdDD.className = 'metric ' + (maxDD !== null ? (maxDD < 15 ? 'positive' : 'negative') : 'neutral');
        tdDD.textContent = maxDD !== null ? maxDD.toFixed(1) + '%' : 'N/A';
        tr.appendChild(tdDD);

        tbody.appendChild(tr);

        // Details row
        var detailsRow = document.createElement('tr');
        detailsRow.className = 'details-row';
        detailsRow.id = 'details-' + pattern.pattern_id;
        var detailsTd = document.createElement('td');
        detailsTd.colSpan = 7;
        var detailsGrid = document.createElement('div');
        detailsGrid.className = 'details-grid';

        var details = [
            ['Total Trades', pattern.total_trades || 0],
            ['Origin', pattern.origin || 'unknown'],
            ['Status', pattern.status || 'untested'],
            ['Profit Factor', (pattern.profit_factor || 0).toFixed(2)],
            ['Timeframe', pattern.timeframe || '--']
        ];

        details.forEach(function(d) {
            var item = document.createElement('div');
            item.className = 'detail-item';
            var label = document.createElement('div');
            label.className = 'detail-label';
            label.textContent = d[0];
            var value = document.createElement('div');
            value.className = 'detail-value';
            value.textContent = d[1];
            item.appendChild(label);
            item.appendChild(value);
            detailsGrid.appendChild(item);
        });

        detailsTd.appendChild(detailsGrid);
        detailsRow.appendChild(detailsTd);
        tbody.appendChild(detailsRow);
    });

        table.appendChild(tbody);
        container.textContent = '';
        container.appendChild(table);

        // Add broken patterns section if there are any (patterns with missing indicators)
        if (brokenPatterns.length > 0) {
            var brokenSection = document.createElement('div');
            brokenSection.className = 'broken-patterns-section';

            var brokenHeader = document.createElement('div');
            brokenHeader.className = 'broken-header';
            var warningIcon = document.createElement('span');
            warningIcon.className = 'warning-icon';
            warningIcon.textContent = '!';
            brokenHeader.appendChild(warningIcon);
            brokenHeader.appendChild(document.createTextNode(' ' + brokenPatterns.length + ' patterns with missing indicators (0 trades)'));
            brokenHeader.onclick = function() {
                var list = document.querySelector('.broken-patterns-list');
                if (list) list.classList.toggle('expanded');
            };
            brokenSection.appendChild(brokenHeader);

            var brokenList = document.createElement('div');
            brokenList.className = 'broken-patterns-list';

            // Lazy loading: only render visible items + buffer
            var visibleCount = 20;  // Initial visible
            var bufferCount = 20;   // Extra loaded for smooth scroll
            var loadedCount = 0;

            function loadMoreBroken() {
                var toLoad = Math.min(visibleCount + bufferCount, brokenPatterns.length) - loadedCount;
                for (var i = 0; i < toLoad && loadedCount < brokenPatterns.length; i++) {
                    var bp = brokenPatterns[loadedCount];
                    var item = document.createElement('div');
                    item.className = 'broken-pattern-item';

                    var pidSpan = document.createElement('span');
                    pidSpan.className = 'pattern-id';
                    pidSpan.textContent = (bp.pattern_id || '').slice(0, 12) + '...';
                    item.appendChild(pidSpan);

                    var originSpan = document.createElement('span');
                    originSpan.className = 'pattern-origin';
                    originSpan.textContent = bp.origin || 'unknown';
                    item.appendChild(originSpan);

                    var runsSpan = document.createElement('span');
                    runsSpan.className = 'pattern-runs';
                    runsSpan.textContent = (bp.total_runs || 0) + ' runs';
                    item.appendChild(runsSpan);

                    brokenList.appendChild(item);
                    loadedCount++;
                }
            }

            // Initial load
            loadMoreBroken();

            // Lazy load on scroll
            brokenList.addEventListener('scroll', function() {
                if (brokenList.scrollTop + brokenList.clientHeight >= brokenList.scrollHeight - 50) {
                    loadMoreBroken();
                }
            });

            brokenSection.appendChild(brokenList);
            container.appendChild(brokenSection);
        }

        // Show untested count if any
        if (untestedPatterns.length > 0) {
            var untestedNote = document.createElement('div');
            untestedNote.className = 'untested-note';
            untestedNote.textContent = untestedPatterns.length + ' patterns pending backtest';
            container.appendChild(untestedNote);
        }

        console.log('Patterns table rendered successfully');
    } catch (err) {
        console.error('Error rendering patterns table:', err);
        container.textContent = 'Error rendering patterns: ' + err.message;
    }
}

function toggleDetails(id) {
    var row = document.getElementById(id);
    if (row) row.classList.toggle('show');
}

// ============================================
// AGENTS PAGE
// ============================================

async function fetchAgentsData() {
    try {
        var results = await Promise.all([
            fetch(API_URL + '/agents?limit=100'),
            fetch(API_URL + '/agents/stats/average')
        ]);

        if (results[0].ok) {
            agentsData = await results[0].json();
            renderAgentsTable();
            renderDistributions();
        }

        if (results[1].ok) {
            var stats = await results[1].json();
            // API returns: active_count, avg_fitness, average_traits
            var activeCount = stats.active_count || stats.count || agentsData.filter(function(a) { return a.is_active; }).length;
            var avgFitness = stats.avg_fitness || stats.average_fitness || 0;
            document.getElementById('stat-agent-active').textContent = activeCount;
            document.getElementById('stat-agent-fitness').textContent = avgFitness ? parseFloat(avgFitness).toFixed(1) : '--';
            // Calculate avg ELO and sortino from agentsData since not in stats
            var totalElo = 0, totalSortino = 0, eloCount = 0, sortinoCount = 0;
            agentsData.forEach(function(a) {
                var elo = parseFloat(a.elo_rating);
                var sortino = parseFloat(a.sortino_ratio);
                if (elo) { totalElo += elo; eloCount++; }
                if (sortino) { totalSortino += sortino; sortinoCount++; }
            });
            document.getElementById('stat-agent-elo').textContent = eloCount > 0 ? (totalElo / eloCount).toFixed(0) : '--';
            document.getElementById('stat-agent-sortino').textContent = sortinoCount > 0 ? (totalSortino / sortinoCount).toFixed(2) : '--';
        }
    } catch (error) {
        console.error('Agents fetch error:', error);
        document.getElementById('agents-table').textContent = 'Error loading agents';
    }
}

function renderAgentsTable() {
    var container = document.getElementById('agents-table');
    if (!container || agentsData.length === 0) {
        if (container) container.textContent = 'No agents found';
        return;
    }

    var sorted = agentsData.slice().sort(function(a, b) {
        return (parseFloat(b[currentSort.agents]) || 0) - (parseFloat(a[currentSort.agents]) || 0);
    });

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    ['RANK', 'AGENT', 'STATUS', 'GEN', 'FITNESS', 'ELO', 'ROI %', 'SORTINO'].forEach(function(text) {
        var th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    sorted.forEach(function(agent, index) {
        var rank = index + 1;
        var fitness = parseFloat(agent.fitness_score) || 0;
        var elo = parseFloat(agent.elo_rating) || 1500;
        var roi = parseFloat(agent.annualized_roi_pct) || 0;
        var sortino = parseFloat(agent.sortino_ratio) || 0;
        var traits = agent.traits || {};

        var tr = document.createElement('tr');
        tr.onclick = function() { toggleDetails('agent-details-' + agent.agent_id); };

        var tdRank = document.createElement('td');
        tdRank.className = 'rank' + (rank <= 3 ? ' rank-' + rank : '');
        tdRank.textContent = rank;
        tr.appendChild(tdRank);

        var tdName = document.createElement('td');
        tdName.style.fontFamily = 'var(--font-mono)';
        tdName.textContent = 'Agent #' + (agent.agent_id || 'N/A').slice(-6);
        tr.appendChild(tdName);

        var tdStatus = document.createElement('td');
        var statusSpan = document.createElement('span');
        statusSpan.style.color = agent.is_active ? 'var(--neon-green)' : 'var(--text-dim)';
        statusSpan.textContent = agent.is_active ? 'ACTIVE' : 'INACTIVE';
        tdStatus.appendChild(statusSpan);
        tr.appendChild(tdStatus);

        var tdGen = document.createElement('td');
        tdGen.textContent = 'Gen ' + (agent.generation || 1);
        tr.appendChild(tdGen);

        var tdFitness = document.createElement('td');
        var fitnessSpan = document.createElement('span');
        fitnessSpan.className = 'metric positive';
        fitnessSpan.textContent = fitness.toFixed(1);
        tdFitness.appendChild(fitnessSpan);
        var fitnessBar = document.createElement('div');
        fitnessBar.className = 'fitness-bar';
        var fitnessFill = document.createElement('div');
        fitnessFill.className = 'fitness-fill';
        fitnessFill.style.width = Math.min(fitness, 100) + '%';
        fitnessBar.appendChild(fitnessFill);
        tdFitness.appendChild(fitnessBar);
        tr.appendChild(tdFitness);

        var tdElo = document.createElement('td');
        tdElo.className = 'metric';
        tdElo.style.color = 'var(--neon-magenta)';
        tdElo.textContent = elo.toFixed(0);
        tr.appendChild(tdElo);

        var tdRoi = document.createElement('td');
        tdRoi.className = 'metric ' + (roi >= 15 ? 'positive' : roi < 0 ? 'negative' : 'neutral');
        tdRoi.textContent = roi.toFixed(1) + '%';
        tr.appendChild(tdRoi);

        var tdSortino = document.createElement('td');
        tdSortino.className = 'metric ' + (sortino >= 1.5 ? 'positive' : sortino < 0.5 ? 'negative' : 'neutral');
        tdSortino.textContent = sortino.toFixed(2);
        tr.appendChild(tdSortino);

        tbody.appendChild(tr);

        // Details row
        var detailsRow = document.createElement('tr');
        detailsRow.className = 'details-row';
        detailsRow.id = 'agent-details-' + agent.agent_id;
        var detailsTd = document.createElement('td');
        detailsTd.colSpan = 8;
        var detailsGrid = document.createElement('div');
        detailsGrid.className = 'details-grid';

        var details = [
            ['Trades', agent.total_trades || 0],
            ['Win Rate', ((parseFloat(agent.win_rate) || 0) * 100).toFixed(1) + '%'],
            ['Sortino', (parseFloat(agent.sortino_ratio) || 0).toFixed(2)],
            ['Max DD', (parseFloat(agent.max_drawdown_pct) || 0).toFixed(1) + '%'],
            ['Risk Tolerance', ((parseFloat(traits.risk_tolerance) || 0) * 100).toFixed(0) + '%'],
            ['Entry Aggression', ((parseFloat(traits.entry_aggression) || 0) * 100).toFixed(0) + '%'],
            ['Exit Aggression', ((parseFloat(traits.exit_aggression) || 0) * 100).toFixed(0) + '%'],
            ['Sentiment Weight', ((parseFloat(traits.sentiment_weight) || 0) * 100).toFixed(0) + '%']
        ];

        details.forEach(function(d) {
            var item = document.createElement('div');
            item.className = 'detail-item';
            var label = document.createElement('div');
            label.className = 'detail-label';
            label.textContent = d[0];
            var value = document.createElement('div');
            value.className = 'detail-value';
            value.textContent = d[1];
            item.appendChild(label);
            item.appendChild(value);
            detailsGrid.appendChild(item);
        });

        detailsTd.appendChild(detailsGrid);
        detailsRow.appendChild(detailsTd);
        tbody.appendChild(detailsRow);
    });

    table.appendChild(tbody);
    container.textContent = '';
    container.appendChild(table);
}

function renderDistributions() {
    renderDistribution('elo-distribution', agentsData.map(function(a) { return parseFloat(a.elo_rating) || 1500; }), [1000, 1250, 1500, 1750, 2000], '#ff00ff');
    renderDistribution('fitness-distribution', agentsData.map(function(a) { return parseFloat(a.fitness_score) || 0; }), [0, 20, 40, 60, 80], '#00ff88');
}

function renderDistribution(canvasId, values, buckets, color) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    var ctx = canvas.getContext('2d');
    var width = canvas.width;
    var height = canvas.height;

    var counts = new Array(buckets.length).fill(0);
    values.forEach(function(v) {
        for (var i = buckets.length - 1; i >= 0; i--) {
            if (v >= buckets[i]) {
                counts[i]++;
                break;
            }
        }
    });

    var maxCount = Math.max.apply(null, counts.concat([1]));
    var barWidth = width / buckets.length - 10;

    ctx.fillStyle = '#1a1a25';
    ctx.fillRect(0, 0, width, height);

    counts.forEach(function(count, index) {
        var barHeight = (count / maxCount) * (height - 20);
        var x = index * (barWidth + 10) + 5;
        var y = height - barHeight - 10;

        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 10;
        ctx.fillRect(x, y, barWidth, barHeight);
        ctx.shadowBlur = 0;
    });
}

// ============================================
// TRADES PAGE
// ============================================

async function fetchTradesData() {
    try {
        var limitEl = document.getElementById('filter-limit');
        var agentEl = document.getElementById('filter-agent');
        var assetEl = document.getElementById('filter-asset');

        var limit = limitEl ? limitEl.value : 100;
        var agentId = agentEl ? agentEl.value : '';
        var asset = assetEl ? assetEl.value : '';

        var url = API_URL + '/trades?limit=' + limit;
        if (agentId) url += '&agent_id=' + agentId;
        if (asset) url += '&symbol=' + asset;

        var response = await fetch(url);
        if (response.ok) {
            tradesData = await response.json();
            renderTradesTable();
            updateTradeStats();
        }
    } catch (error) {
        console.error('Trades fetch error:', error);
        document.getElementById('trades-table').textContent = 'Error loading trades';
    }
}

function renderTradesTable() {
    var container = document.getElementById('trades-table');
    if (!container || tradesData.length === 0) {
        if (container) container.textContent = 'No trades found';
        return;
    }

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    ['TIME', 'AGENT', 'ASSET', 'SIDE', 'ENTRY', 'EXIT', 'P&L', 'ROI %'].forEach(function(text) {
        var th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    tradesData.forEach(function(trade) {
        var pnl = trade.pnl_usd || 0;
        var roi = trade.net_pnl_pct || trade.gross_pnl_pct || 0;
        var time = trade.exit_timestamp ? new Date(trade.exit_timestamp).toLocaleString() : '--';

        var tr = document.createElement('tr');

        var tdTime = document.createElement('td');
        tdTime.style.fontSize = '0.8em';
        tdTime.style.color = 'var(--text-secondary)';
        tdTime.textContent = time;
        tr.appendChild(tdTime);

        var tdAgent = document.createElement('td');
        tdAgent.style.fontFamily = 'var(--font-mono)';
        tdAgent.style.fontSize = '0.8em';
        tdAgent.textContent = (trade.agent_id || 'N/A').slice(-6);
        tr.appendChild(tdAgent);

        var tdAsset = document.createElement('td');
        tdAsset.textContent = trade.symbol || 'N/A';
        tr.appendChild(tdAsset);

        var tdSide = document.createElement('td');
        var sideUpper = (trade.side || '').toUpperCase();
        tdSide.style.color = sideUpper === 'LONG' ? 'var(--neon-green)' : 'var(--neon-red)';
        tdSide.textContent = sideUpper || 'N/A';
        tr.appendChild(tdSide);

        var tdEntry = document.createElement('td');
        tdEntry.className = 'metric';
        tdEntry.textContent = trade.entry_price ? trade.entry_price.toFixed(2) : '--';
        tr.appendChild(tdEntry);

        var tdExit = document.createElement('td');
        tdExit.className = 'metric';
        tdExit.textContent = trade.exit_price ? trade.exit_price.toFixed(2) : '--';
        tr.appendChild(tdExit);

        var tdPnl = document.createElement('td');
        tdPnl.className = 'metric ' + (pnl >= 0 ? 'positive' : 'negative');
        tdPnl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
        tr.appendChild(tdPnl);

        var tdRoi = document.createElement('td');
        tdRoi.className = 'metric ' + (roi >= 0 ? 'positive' : 'negative');
        tdRoi.textContent = (roi >= 0 ? '+' : '') + roi.toFixed(2) + '%';
        tr.appendChild(tdRoi);

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    container.textContent = '';
    container.appendChild(table);
}

function updateTradeStats() {
    var totalPnl = tradesData.reduce(function(sum, t) { return sum + (t.pnl_usd || 0); }, 0);
    var wins = tradesData.filter(function(t) { return t.is_winner === true || (t.pnl_usd || 0) > 0; }).length;
    var winRate = tradesData.length > 0 ? (wins / tradesData.length) * 100 : 0;
    var avgTrade = tradesData.length > 0 ? totalPnl / tradesData.length : 0;

    document.getElementById('stat-trade-total').textContent = tradesData.length;
    document.getElementById('stat-trade-pnl').textContent = (totalPnl >= 0 ? '+' : '') + totalPnl.toFixed(2);
    document.getElementById('stat-trade-winrate').textContent = winRate.toFixed(1) + '%';
    document.getElementById('stat-trade-avg').textContent = (avgTrade >= 0 ? '+' : '') + avgTrade.toFixed(2);
}

// ============================================
// ACTIVITY LOG
// ============================================

function addLogEntry(component, message) {
    var log = document.getElementById('activity-log');
    if (!log) return;

    var entry = document.createElement('div');
    entry.className = 'log-entry';

    var now = new Date();
    var time = now.toLocaleTimeString('en-US', { hour12: false });

    var timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = time;
    entry.appendChild(timeSpan);

    var compSpan = document.createElement('span');
    compSpan.className = 'log-component';
    compSpan.textContent = '[' + component + ']';
    entry.appendChild(compSpan);

    var msgSpan = document.createElement('span');
    msgSpan.className = 'log-message';
    msgSpan.textContent = message;
    entry.appendChild(msgSpan);

    log.insertBefore(entry, log.firstChild);

    while (log.children.length > 50) {
        log.removeChild(log.lastChild);
    }
}

// =============================================================================
// TASKMASTER PAGE FUNCTIONS
// =============================================================================

async function loadTaskmasterData() {
    try {
        // Fetch health data
        var healthRes = await fetch(API_URL + '/taskmaster/health');
        if (healthRes.ok) {
            var health = await healthRes.json();
            updateTaskmasterHealth(health);
        }

        // Fetch activity log
        var activityRes = await fetch(API_URL + '/taskmaster/activity?limit=20');
        if (activityRes.ok) {
            var activity = await activityRes.json();
            updateTaskmasterActivity(activity.activity);
        }

        // Fetch alerts
        var alertsRes = await fetch(API_URL + '/taskmaster/alerts');
        if (alertsRes.ok) {
            var alerts = await alertsRes.json();
            updateTaskmasterAlerts(alerts.alerts);
        }
    } catch (error) {
        console.error('Taskmaster data fetch error:', error);
    }
}

function updateTaskmasterHealth(health) {
    // Update summary stats
    var statusEl = document.getElementById('tm-system-status');
    if (statusEl) {
        statusEl.textContent = health.status.toUpperCase();
        statusEl.className = 'stat-value ' + health.status;
    }

    var summary = health.summary || {};
    setText('tm-component-count', summary.total_components || 0);
    setText('tm-checks', summary.checks_performed || 0);
    setText('tm-pokes', summary.pokes_sent || 0);

    // Format uptime
    var uptime = summary.uptime_seconds || 0;
    var uptimeStr = formatDuration(uptime);
    setText('tm-uptime', uptimeStr);

    // Update components grid
    var grid = document.getElementById('tm-components-grid');
    if (grid && health.components) {
        grid.replaceChildren();
        Object.keys(health.components).forEach(function(compId) {
            var comp = health.components[compId];
            var card = createComponentCard(compId, comp);
            grid.appendChild(card);
        });
    }
}

function createComponentCard(compId, comp) {
    var card = document.createElement('div');
    card.className = 'component-card status-' + comp.status;

    var name = document.createElement('div');
    name.className = 'component-name';
    name.textContent = comp.name || compId;
    card.appendChild(name);

    var status = document.createElement('span');
    status.className = 'component-status ' + comp.status;
    status.textContent = comp.status.toUpperCase();
    card.appendChild(status);

    var meta = document.createElement('div');
    meta.className = 'component-meta';

    if (comp.metadata) {
        if (comp.metadata.current_phase) {
            var phase = document.createElement('div');
            var phaseLabel = document.createElement('span');
            phaseLabel.textContent = 'Phase: ';
            phase.appendChild(phaseLabel);
            phase.appendChild(document.createTextNode(comp.metadata.current_phase));
            meta.appendChild(phase);
        }
        if (comp.metadata.cycles_completed !== undefined) {
            var cycles = document.createElement('div');
            var cyclesLabel = document.createElement('span');
            cyclesLabel.textContent = 'Cycles: ';
            cycles.appendChild(cyclesLabel);
            cycles.appendChild(document.createTextNode(comp.metadata.cycles_completed));
            meta.appendChild(cycles);
        }
    }

    if (comp.poke_count > 0) {
        var pokes = document.createElement('div');
        var pokesLabel = document.createElement('span');
        pokesLabel.textContent = 'Pokes: ';
        pokes.appendChild(pokesLabel);
        pokes.appendChild(document.createTextNode(comp.poke_count));
        meta.appendChild(pokes);
    }

    card.appendChild(meta);
    return card;
}

function updateTaskmasterActivity(activities) {
    var log = document.getElementById('tm-activity-log');
    if (!log) return;

    log.replaceChildren();

    if (!activities || activities.length === 0) {
        var noData = document.createElement('div');
        noData.className = 'no-alerts';
        noData.textContent = 'No recent activity';
        log.appendChild(noData);
        return;
    }

    activities.forEach(function(act) {
        var entry = document.createElement('div');
        entry.className = 'activity-entry level-' + act.level;

        var time = document.createElement('span');
        time.className = 'activity-time';
        time.textContent = formatTime(act.timestamp);
        entry.appendChild(time);

        var comp = document.createElement('span');
        comp.className = 'activity-component';
        comp.textContent = act.component_id;
        entry.appendChild(comp);

        var action = document.createElement('span');
        action.className = 'activity-action';
        action.textContent = act.action;
        entry.appendChild(action);

        var details = document.createElement('span');
        details.className = 'activity-details';
        details.textContent = act.details;
        entry.appendChild(details);

        log.appendChild(entry);
    });
}

function updateTaskmasterAlerts(alerts) {
    var container = document.getElementById('tm-alerts');
    if (!container) return;

    container.replaceChildren();

    if (!alerts || alerts.length === 0) {
        var noAlerts = document.createElement('div');
        noAlerts.className = 'no-alerts';
        noAlerts.textContent = 'No active alerts';
        container.appendChild(noAlerts);
        return;
    }

    alerts.forEach(function(alert) {
        var item = document.createElement('div');
        item.className = 'alert-item ' + alert.level;

        var content = document.createElement('div');
        content.className = 'alert-content';

        var title = document.createElement('div');
        title.className = 'alert-title';
        title.textContent = alert.component_id + ': ' + alert.action;
        content.appendChild(title);

        var details = document.createElement('div');
        details.textContent = alert.details;
        content.appendChild(details);

        var time = document.createElement('div');
        time.className = 'alert-time';
        time.textContent = formatTime(alert.timestamp);
        content.appendChild(time);

        item.appendChild(content);
        container.appendChild(item);
    });
}

function formatTime(timestamp) {
    if (!timestamp) return '--:--';
    var d = new Date(timestamp);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

function formatDuration(seconds) {
    if (seconds < 60) return Math.floor(seconds) + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    var hours = Math.floor(seconds / 3600);
    var mins = Math.floor((seconds % 3600) / 60);
    return hours + 'h ' + mins + 'm';
}

function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

// Taskmaster Intervention Functions (called by button onclick)
async function pokeOrchestrator() {
    try {
        var res = await fetch(API_URL + '/taskmaster/poke/orchestrator', { method: 'POST' });
        var result = await res.json();
        alert('Poke sent: ' + (result.message || 'OK'));
        loadTaskmasterData();
    } catch (e) {
        alert('Poke failed: ' + e.message);
    }
}

async function clearErrors() {
    try {
        var res = await fetch(API_URL + '/taskmaster/clear-errors', { method: 'POST' });
        var result = await res.json();
        alert('Errors cleared: ' + (result.message || 'OK'));
        loadTaskmasterData();
    } catch (e) {
        alert('Clear errors failed: ' + e.message);
    }
}

async function skipPhase() {
    if (!confirm('Skip the current orchestrator phase?')) return;
    try {
        var res = await fetch(API_URL + '/taskmaster/skip-phase', { method: 'POST' });
        var result = await res.json();
        alert('Phase skipped: ' + (result.skipped_phase || 'OK'));
        loadTaskmasterData();
    } catch (e) {
        alert('Skip phase failed: ' + e.message);
    }
}

async function restartOrchestrator() {
    if (!confirm('RESTART the orchestrator? This will stop and restart the pipeline.')) return;
    try {
        var res = await fetch(API_URL + '/taskmaster/restart/orchestrator', { method: 'POST' });
        var result = await res.json();
        alert('Orchestrator restarted: ' + (result.message || 'OK'));
        loadTaskmasterData();
    } catch (e) {
        alert('Restart failed: ' + e.message);
    }
}

async function forceEvolution() {
    if (!confirm('Force an evolution cycle now?')) return;
    try {
        var res = await fetch(API_URL + '/taskmaster/force/evolution', { method: 'POST' });
        var result = await res.json();
        alert('Evolution triggered: ' + JSON.stringify(result));
        loadTaskmasterData();
    } catch (e) {
        alert('Force evolution failed: ' + e.message);
    }
}

async function forceCrucible() {
    if (!confirm('Force a Crucible eligibility check now?')) return;
    try {
        var res = await fetch(API_URL + '/taskmaster/force/crucible', { method: 'POST' });
        var result = await res.json();
        alert('Crucible check triggered: ' + JSON.stringify(result));
        loadTaskmasterData();
    } catch (e) {
        alert('Force crucible failed: ' + e.message);
    }
}

// =============================================================================
// TRADING PAGE FUNCTIONS
// =============================================================================

async function loadTradingData() {
    try {
        // Populate agent dropdown
        await populateAgentDropdown();

        // Fetch active paper trading agents
        await fetchActivePaperAgents();

        // Fetch Bear Protection regime data
        fetchTradingRegimeData();

        // Fetch recent live trades
        var tradesRes = await fetch(API_URL + '/trading/trades/recent?limit=20');
        if (tradesRes.ok) {
            var trades = await tradesRes.json();
            updateLiveTradesTable(trades);
        }

        // Fetch positions
        var posRes = await fetch(API_URL + '/trading/positions');
        if (posRes.ok) {
            var positions = await posRes.json();
            setText('trading-open-positions', positions.length || 0);
        }

        // Fetch approval queue stats
        var queueRes = await fetch(API_URL + '/trading/approval/stats');
        if (queueRes.ok) {
            var stats = await queueRes.json();
            setText('trading-pending', stats.total_pending || 0);
        }
        // Connect decision feed SSE
        connectDecisionFeed();
    } catch (error) {
        console.error('Trading data fetch error:', error);
    }
}

async function populateAgentDropdown() {
    try {
        var results = await Promise.all([
            fetch(API_URL + '/agents?limit=50').then(function(r) { return r.ok ? r.json() : []; }).catch(function(err) { console.error('populateAgentDropdown: agents fetch failed:', err); return []; }),
            fetch(API_URL + '/trading/paper/status').then(function(r) { return r.ok ? r.json() : []; }).catch(function() { return []; }),
            fetch(API_URL + '/trading/positions').then(function(r) { return r.ok ? r.json() : []; }).catch(function() { return []; }),
        ]);

        var agents = results[0];
        var activeAgents = results[1];
        var dbPositions = results[2];

        var select = document.getElementById('trading-agent-select');
        if (!select) return;

        // Build set of actively trading agent IDs (to exclude from dropdown)
        var tradingAgentIds = {};
        activeAgents.forEach(function(a) { tradingAgentIds[a.agent_id] = true; });

        // Count open positions per agent (endpoint already filters status='open')
        var positionCounts = {};
        dbPositions.forEach(function(p) {
            positionCounts[p.agent_id] = (positionCounts[p.agent_id] || 0) + 1;
        });

        // Clear existing options (keep the first placeholder)
        while (select.options.length > 1) {
            select.remove(1);
        }

        // Filter: active agents not currently trading
        var eligible = agents.filter(function(a) {
            return a.is_active && !tradingAgentIds[a.agent_id];
        });

        // Diagnostics: log agent counts to help debug eligibility issues
        console.error('populateAgentDropdown: ' + agents.length + ' total agents, ' + eligible.length + ' eligible (active + not already trading)');

        // If no eligible agents, show a disabled placeholder
        if (eligible.length === 0) {
            var noAgentOption = document.createElement('option');
            noAgentOption.value = '';
            noAgentOption.disabled = true;
            noAgentOption.selected = true;
            noAgentOption.textContent = '(No available agents)';
            select.appendChild(noAgentOption);
            return;
        }

        // Sort by best regime fitness descending
        eligible.sort(function(a, b) {
            return getBestRegimeFitness(b).score - getBestRegimeFitness(a).score;
        });

        eligible.forEach(function(agent) {
            var option = document.createElement('option');
            option.value = agent.agent_id;

            var regime = getBestRegimeFitness(agent);
            var posCount = positionCounts[agent.agent_id] || 0;

            // Format: Name | REGIME:score | S:x DD:y% CAGR:z% | N pos
            var label = (agent.name || '#' + agent.agent_id.slice(-6));
            label += ' | ' + regime.regime.toUpperCase() + ':' + regime.score.toFixed(0);

            // Key stats
            var stats = [];
            if (agent.sortino_ratio) stats.push('S:' + parseFloat(agent.sortino_ratio).toFixed(1));
            if (agent.max_drawdown_pct) stats.push('DD:' + parseFloat(agent.max_drawdown_pct).toFixed(0) + '%');
            if (agent.annualized_roi_pct) stats.push('CAGR:' + parseFloat(agent.annualized_roi_pct).toFixed(0) + '%');
            if (stats.length > 0) label += ' ' + stats.join(' ');

            if (posCount > 0) label += ' | ' + posCount + ' pos';

            option.textContent = label;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Error populating agent dropdown:', e);
    }
}

function getBestRegimeFitness(agent) {
    var fbr = agent.fitness_by_regime;
    if (!fbr || typeof fbr !== 'object') {
        return { regime: '?', score: parseFloat(agent.fitness_score) || 0 };
    }
    var bestRegime = '?';
    var bestScore = 0;
    Object.keys(fbr).forEach(function(regime) {
        var val = fbr[regime];
        var score = (typeof val === 'number') ? val : (val && val.fitness ? val.fitness : 0);
        if (score > bestScore) {
            bestScore = score;
            bestRegime = regime;
        }
    });
    if (bestScore === 0) {
        return { regime: '?', score: parseFloat(agent.fitness_score) || 0 };
    }
    return { regime: bestRegime, score: bestScore };
}

async function fetchActivePaperAgents() {
    try {
        // Ensure prices are available before rendering P&L
        await ensureLatestPrices();

        var res = await fetch(API_URL + '/trading/paper/status');
        if (!res.ok) return;
        var agents = await res.json();

        if (agents && agents.length > 0) {
            setText('trading-active-agents', agents.length);
            renderActivePaperAgents(agents);
        } else {
            // No active sessions - check DB for orphaned positions
            setText('trading-active-agents', 0);
            var posRes = await fetch(API_URL + '/trading/positions');
            if (posRes.ok) {
                var dbPositions = await posRes.json();
                if (dbPositions && dbPositions.length > 0) {
                    renderOrphanedPositions(dbPositions);
                } else {
                    renderActivePaperAgents([]);
                }
            } else {
                renderActivePaperAgents([]);
            }
        }
    } catch (e) {
        console.error('Error fetching active paper agents:', e);
    }
}

function renderActivePaperAgents(agents) {
    var container = document.getElementById('active-paper-agents');
    if (!container) return;

    container.replaceChildren();

    if (!agents || agents.length === 0) {
        var noData = document.createElement('div');
        noData.className = 'no-data';
        noData.textContent = 'No active paper trading sessions';
        container.appendChild(noData);
        return;
    }

    agents.forEach(function(agent) {
        var card = document.createElement('div');
        var statusClass = agent.status === 'paused' ? 'paused' : 'trading';
        card.className = 'active-agent-card ' + statusClass;

        // Header with name and status badge
        var header = document.createElement('div');
        header.className = 'active-agent-header';

        var name = document.createElement('span');
        name.className = 'active-agent-name';
        name.textContent = agent.agent_name || ('Agent #' + agent.agent_id.slice(-6));
        header.appendChild(name);

        var status = document.createElement('span');
        status.className = 'active-agent-status ' + statusClass;
        status.textContent = agent.status === 'paused' ? 'PAUSED' : 'TRADING';
        header.appendChild(status);

        card.appendChild(header);

        // Symbols being watched
        var symbolsRow = document.createElement('div');
        symbolsRow.className = 'agent-symbols-row';
        var symbolsLabel = document.createElement('span');
        symbolsLabel.className = 'agent-symbols-label';
        symbolsLabel.textContent = 'Watching: ';
        symbolsRow.appendChild(symbolsLabel);
        var symbols = agent.symbols || [];
        symbols.forEach(function(sym) {
            var badge = document.createElement('span');
            badge.className = 'symbol-badge';
            badge.textContent = sym;
            symbolsRow.appendChild(badge);
        });
        card.appendChild(symbolsRow);

        // Stats row
        var stats = document.createElement('div');
        stats.className = 'active-agent-stats';

        var pnlPct = agent.total_pnl_pct || 0;
        var pnlClass = pnlPct >= 0 ? 'positive' : 'negative';
        var pnlSign = pnlPct >= 0 ? '+' : '';

        var statItems = [
            { label: 'Balance', value: '$' + (agent.balance || 0).toLocaleString(undefined, {minimumFractionDigits: 2}) },
            { label: 'Initial', value: '$' + (agent.initial_balance || 0).toLocaleString(undefined, {minimumFractionDigits: 0}) },
            { label: 'Trades', value: agent.trades_count || 0 },
            { label: 'P&L', value: pnlSign + '$' + Math.abs(agent.total_pnl || 0).toFixed(2) + ' (' + pnlSign + pnlPct.toFixed(1) + '%)', pnlClass: pnlClass }
        ];

        statItems.forEach(function(item) {
            var stat = document.createElement('div');
            stat.className = 'active-agent-stat';

            var label = document.createElement('span');
            label.className = 'active-agent-stat-label';
            label.textContent = item.label;
            stat.appendChild(label);

            var value = document.createElement('span');
            value.className = 'active-agent-stat-value' + (item.pnlClass ? ' ' + item.pnlClass : '');
            value.textContent = item.value;
            stat.appendChild(value);

            stats.appendChild(stat);
        });

        card.appendChild(stats);

        // Open Positions section (per lot with running stats)
        var positionsSection = document.createElement('div');
        positionsSection.className = 'agent-positions-section';

        var positionsHeader = document.createElement('div');
        positionsHeader.className = 'agent-positions-header';
        positionsHeader.textContent = 'OPEN POSITIONS (' + (agent.positions || 0) + ')';
        positionsSection.appendChild(positionsHeader);

        var openPositions = agent.open_positions || [];
        if (openPositions.length === 0) {
            var noPos = document.createElement('div');
            noPos.className = 'no-positions';
            noPos.textContent = 'No open positions';
            positionsSection.appendChild(noPos);
        } else {
            openPositions.forEach(function(pos) {
                var posCard = buildPositionLotCard(pos, agent.agent_id);
                positionsSection.appendChild(posCard);
            });
        }

        card.appendChild(positionsSection);

        // Action buttons for this agent
        var actions = document.createElement('div');
        actions.className = 'agent-card-actions';

        var pauseBtn = document.createElement('button');
        pauseBtn.className = 'action-btn warning agent-card-btn';
        pauseBtn.textContent = agent.status === 'paused' ? 'RESUME' : 'PAUSE';
        pauseBtn.onclick = function(e) {
            e.stopPropagation();
            if (agent.status === 'paused') {
                resumeTradingForAgent(agent.agent_id);
            } else {
                pauseTradingForAgent(agent.agent_id);
            }
        };
        actions.appendChild(pauseBtn);

        var stopBtn = document.createElement('button');
        stopBtn.className = 'action-btn danger agent-card-btn';
        stopBtn.textContent = 'STOP';
        stopBtn.onclick = function(e) {
            e.stopPropagation();
            stopPaperTradingForAgent(agent.agent_id, agent.agent_name);
        };
        actions.appendChild(stopBtn);

        var closeBtn = document.createElement('button');
        closeBtn.className = 'action-btn agent-card-btn';
        closeBtn.textContent = 'CLOSE POS';
        closeBtn.onclick = function(e) {
            e.stopPropagation();
            closePositionsForAgent(agent.agent_id);
        };
        actions.appendChild(closeBtn);

        card.appendChild(actions);
        container.appendChild(card);
    });
}

// Direct agent card action functions
async function pauseTradingForAgent(agentId) {
    try {
        var res = await fetch(API_URL + '/trading/override/pause/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            loadTradingData();
        } else {
            alert('Failed to pause: ' + (result.detail || 'Unknown error'));
        }
    } catch(e) {
        alert('Error: ' + e.message);
    }
}

async function resumeTradingForAgent(agentId) {
    try {
        var res = await fetch(API_URL + '/trading/override/resume/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            loadTradingData();
        } else {
            alert('Failed to resume: ' + (result.detail || 'Unknown error'));
        }
    } catch(e) {
        alert('Error: ' + e.message);
    }
}

async function stopPaperTradingForAgent(agentId, agentName) {
    if (!confirm('Stop paper trading for ' + (agentName || agentId) + '?')) return;
    try {
        var res = await fetch(API_URL + '/trading/paper/stop/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            alert('Stopped. Trades: ' + (result.trades_count || 0) + ', P&L: $' + (result.total_pnl || 0).toFixed(2));
            loadTradingData();
        } else {
            alert('Failed to stop: ' + (result.detail || 'Unknown error'));
        }
    } catch(e) {
        alert('Error: ' + e.message);
    }
}

async function closePositionsForAgent(agentId) {
    if (!confirm('Close all positions for this agent?')) return;
    try {
        // Ensure prices are available from API if WebSocket hasn't pushed yet
        await ensureLatestPrices();
        var prices = {};
        if (latestPrices.BTC > 0) prices['BTC-USDT'] = latestPrices.BTC;
        if (latestPrices.ETH > 0) prices['ETH-USDT'] = latestPrices.ETH;
        if (latestPrices.SOL > 0) prices['SOL-USDT'] = latestPrices.SOL;

        var res = await fetch(API_URL + '/trading/override/close-all/' + agentId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_prices: prices })
        });
        var result = await res.json();
        if (res.ok) {
            alert('Closed ' + (result.positions_closed || 0) + ' positions. P&L: $' + (result.total_pnl_usd || 0).toFixed(2));
            loadTradingData();
        } else {
            alert('Failed to close: ' + (result.detail || 'Unknown error'));
        }
    } catch(e) {
        alert('Error: ' + e.message);
    }
}

// Position Helpers

function buildPositionLotCard(pos, agentId) {
    var posCard = document.createElement('div');
    posCard.className = 'position-lot-card';

    // Row 1: Symbol, Side, Entry Price
    var posHeader = document.createElement('div');
    posHeader.className = 'position-lot-header';

    var posSymbol = document.createElement('span');
    posSymbol.className = 'position-symbol';
    posSymbol.textContent = pos.symbol;
    posHeader.appendChild(posSymbol);

    var posSide = document.createElement('span');
    posSide.className = 'position-side ' + (pos.side === 'long' ? 'long' : 'short');
    posSide.textContent = pos.side.toUpperCase();
    posHeader.appendChild(posSide);

    var posEntry = document.createElement('span');
    posEntry.className = 'position-entry';
    posEntry.textContent = '@ $' + pos.entry_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    posHeader.appendChild(posEntry);

    posCard.appendChild(posHeader);

    // Row 2: Running stats (size, value, unrealized P&L, duration)
    var posStats = document.createElement('div');
    posStats.className = 'position-lot-stats';

    var sizeEl = document.createElement('span');
    sizeEl.className = 'position-lot-stat';
    sizeEl.textContent = 'Size: ' + (pos.size || 0).toFixed(6);
    posStats.appendChild(sizeEl);

    var sizeUsd = pos.size_usd || 0;
    var valueEl = document.createElement('span');
    valueEl.className = 'position-lot-stat';
    valueEl.textContent = 'Value: $' + sizeUsd.toFixed(2);
    posStats.appendChild(valueEl);

    // Unrealized P&L (computed from latestPrices)
    var currentPrice = getSymbolPrice(pos.symbol);
    var unrealizedPnlPct = 0;
    var unrealizedPnlUsd = 0;
    if (currentPrice > 0 && pos.entry_price > 0) {
        if (pos.side === 'long') {
            unrealizedPnlPct = ((currentPrice - pos.entry_price) / pos.entry_price) * 100;
        } else {
            unrealizedPnlPct = ((pos.entry_price - currentPrice) / pos.entry_price) * 100;
        }
        unrealizedPnlUsd = sizeUsd * (unrealizedPnlPct / 100);
    }

    var pnlClass = unrealizedPnlPct >= 0 ? 'positive' : 'negative';
    var pnlSign = unrealizedPnlPct >= 0 ? '+' : '-';

    var pnlEl = document.createElement('span');
    pnlEl.className = 'position-lot-stat position-pnl ' + pnlClass;
    pnlEl.textContent = 'P&L: ' + pnlSign + Math.abs(unrealizedPnlPct).toFixed(2) + '% (' + pnlSign + '$' + Math.abs(unrealizedPnlUsd).toFixed(2) + ')';
    posStats.appendChild(pnlEl);

    // Duration
    var durationStr = '--';
    if (pos.duration_seconds) {
        durationStr = formatDuration(pos.duration_seconds);
    } else if (pos.entry_time) {
        var elapsed = (Date.now() - new Date(pos.entry_time).getTime()) / 1000;
        durationStr = formatDuration(elapsed);
    }
    var durEl = document.createElement('span');
    durEl.className = 'position-lot-stat';
    durEl.textContent = 'Duration: ' + durationStr;
    posStats.appendChild(durEl);

    posCard.appendChild(posStats);

    // Close button
    var closeLotBtn = document.createElement('button');
    closeLotBtn.className = 'action-btn danger position-close-btn';
    closeLotBtn.textContent = 'CLOSE';
    closeLotBtn.onclick = (function(aId, sym, tId) {
        return function(e) {
            e.stopPropagation();
            closeSinglePosition(aId, sym, tId);
        };
    })(agentId, pos.symbol, pos.trade_id);
    posCard.appendChild(closeLotBtn);

    return posCard;
}

function renderOrphanedPositions(positions) {
    var container = document.getElementById('active-paper-agents');
    if (!container) return;
    container.replaceChildren();

    var header = document.createElement('div');
    header.className = 'agent-positions-header';
    header.textContent = 'OPEN POSITIONS (session stopped) - ' + positions.length + ' lot(s)';
    header.style.marginBottom = '12px';
    container.appendChild(header);

    positions.forEach(function(pos) {
        var posCard = buildPositionLotCard(pos, pos.agent_id || 'unknown');
        container.appendChild(posCard);
    });
}

function getSymbolPrice(symbol) {
    // Map trading symbol to latestPrices key
    if (symbol.indexOf('BTC') >= 0) return latestPrices.BTC || 0;
    if (symbol.indexOf('ETH') >= 0) return latestPrices.ETH || 0;
    if (symbol.indexOf('SOL') >= 0) return latestPrices.SOL || 0;
    return 0;
}

async function ensureLatestPrices() {
    // Fetch prices from API if WebSocket hasn't pushed data yet
    var symbols = ['BTC', 'ETH', 'SOL'];
    var needed = symbols.filter(function(s) { return !latestPrices[s] || latestPrices[s] <= 0; });
    if (needed.length === 0) return;

    var fetches = needed.map(function(sym) {
        return fetch(API_URL + '/market_data/price/' + sym)
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; });
    });
    var results = await Promise.all(fetches);
    results.forEach(function(data, i) {
        if (data && data.price > 0) {
            latestPrices[needed[i]] = data.price;
        }
    });
}

async function closeSinglePosition(agentId, symbol, tradeId) {
    if (!confirm('Close ' + symbol + ' position?')) return;
    try {
        var currentPrice = getSymbolPrice(symbol);
        if (currentPrice <= 0) {
            // Try fetching from API before giving up
            await ensureLatestPrices();
            currentPrice = getSymbolPrice(symbol);
        }
        if (currentPrice <= 0) {
            alert('No live price available for ' + symbol + '. Cannot close.');
            return;
        }
        var res = await fetch(API_URL + '/trading/positions/' + encodeURIComponent(symbol) + '/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: agentId, current_price: currentPrice })
        });
        var result = await res.json();
        if (res.ok) {
            var pnlSign = (result.pnl_pct || 0) >= 0 ? '+' : '';
            alert('Closed ' + symbol + ': ' + pnlSign + (result.pnl_pct || 0).toFixed(2) + '% ($' + (result.pnl_usd || 0).toFixed(2) + ')');
            loadTradingData();
        } else {
            alert('Failed to close: ' + (result.detail || 'Unknown error'));
        }
    } catch(e) {
        alert('Error: ' + e.message);
    }
}

// Auto-refresh positions every 10 seconds when trading page is active
var positionRefreshInterval = null;

function startPositionRefresh() {
    if (positionRefreshInterval) return;
    positionRefreshInterval = setInterval(function() {
        if (currentPage === 'trading') {
            fetchActivePaperAgents();
        }
    }, 10000);
}

function stopPositionRefresh() {
    if (positionRefreshInterval) {
        clearInterval(positionRefreshInterval);
        positionRefreshInterval = null;
    }
}

// Trading Control Functions
function getSelectedAgentId() {
    var select = document.getElementById('trading-agent-select');
    return select ? select.value : '';
}

function getSelectedSymbols() {
    var select = document.getElementById('trading-symbol-select');
    if (!select) return ['BTC-USDT'];
    var selected = [];
    for (var i = 0; i < select.options.length; i++) {
        if (select.options[i].selected) {
            selected.push(select.options[i].value);
        }
    }
    return selected.length > 0 ? selected : ['BTC-USDT'];
}

function getInitialBalance() {
    var input = document.getElementById('trading-balance-input');
    return input ? parseFloat(input.value) || 10000 : 10000;
}

async function startPaperTrading() {
    var agentId = getSelectedAgentId();
    if (!agentId) {
        alert('Please select an agent first');
        return;
    }

    var symbols = getSelectedSymbols();
    var balance = getInitialBalance();

    try {
        var res = await fetch(API_URL + '/trading/paper/start/' + agentId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: symbols, initial_balance: balance })
        });

        var result = await res.json();
        if (res.ok) {
            alert('Paper trading started for ' + (result.agent_name || agentId));
            loadTradingData();
        } else {
            alert('Failed to start paper trading: ' + (result.detail || result.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error starting paper trading: ' + e.message);
    }
}

async function stopPaperTrading() {
    var agentId = getSelectedAgentId();
    if (!agentId) {
        alert('Please select an agent first');
        return;
    }

    if (!confirm('Stop paper trading for this agent?')) return;

    try {
        var res = await fetch(API_URL + '/trading/paper/stop/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            alert('Paper trading stopped. Trades: ' + (result.trades_count || 0) + ', P&L: $' + (result.total_pnl || 0).toFixed(2));
            loadTradingData();
        } else {
            alert('Failed to stop paper trading: ' + (result.detail || result.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error stopping paper trading: ' + e.message);
    }
}

async function pauseTrading() {
    var agentId = getSelectedAgentId();
    if (!agentId) {
        alert('Please select an agent first');
        return;
    }

    try {
        var res = await fetch(API_URL + '/trading/override/pause/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            alert('Trading paused for agent');
            loadTradingData();
        } else {
            alert('Failed to pause: ' + (result.detail || result.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error pausing trading: ' + e.message);
    }
}

async function resumeTrading() {
    var agentId = getSelectedAgentId();
    if (!agentId) {
        alert('Please select an agent first');
        return;
    }

    try {
        var res = await fetch(API_URL + '/trading/override/resume/' + agentId, { method: 'POST' });
        var result = await res.json();
        if (res.ok) {
            alert('Trading resumed for agent');
            loadTradingData();
        } else {
            alert('Failed to resume: ' + (result.detail || result.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error resuming trading: ' + e.message);
    }
}

function startLiveTrading() {
    alert('Live trading is not implemented yet. This is a checkpoint for MVP.\n\nUse Paper Trading to test agents first.');
}

function stopLiveTrading() {
    alert('Live trading is not implemented yet.');
}

async function closeAllPositions() {
    var agentId = getSelectedAgentId();
    if (!agentId) {
        alert('Please select an agent first');
        return;
    }

    if (!confirm('CLOSE ALL POSITIONS for this agent? This cannot be undone.')) return;

    try {
        // Ensure prices are available from API if WebSocket hasn't pushed yet
        await ensureLatestPrices();
        var prices = {};
        if (latestPrices.BTC > 0) prices['BTC-USDT'] = latestPrices.BTC;
        if (latestPrices.ETH > 0) prices['ETH-USDT'] = latestPrices.ETH;
        if (latestPrices.SOL > 0) prices['SOL-USDT'] = latestPrices.SOL;

        var res = await fetch(API_URL + '/trading/override/close-all/' + agentId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_prices: prices })
        });

        var result = await res.json();
        if (res.ok) {
            alert('Closed ' + (result.positions_closed || 0) + ' positions. Total P&L: $' + (result.total_pnl_usd || 0).toFixed(2));
            loadTradingData();
        } else {
            alert('Failed to close positions: ' + (result.detail || result.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error closing positions: ' + e.message);
    }
}

async function fetchTradingRegimeData() {
    try {
        var res = await fetch(API_URL + '/market_data/regime');
        if (!res.ok) return;
        var data = await res.json();

        // Get portfolio-weighted regime
        var portfolio = data.portfolio || {};
        var regime = portfolio.effective_regime || 'NEUTRAL';
        var weightedScore = portfolio.weighted_regime_score || 0;

        // Update regime badge on Trading page
        var badge = document.getElementById('trading-regime-badge');
        if (badge) {
            badge.textContent = regime;
            badge.className = 'regime-badge regime-' + regime.toLowerCase();
        }

        // Update weighted score display
        var trigger = document.getElementById('trading-regime-trigger');
        if (trigger) {
            var scoreDisplay = weightedScore >= 0 ? '+' + weightedScore.toFixed(2) : weightedScore.toFixed(2);
            trigger.textContent = 'Score: ' + scoreDisplay;
        }

        // Update utilization bar
        var util = data.utilization || {};
        var investedPct = util.invested_pct || 0;
        var limitPct = util.limit_pct || portfolio.max_position_pct || 65;

        var fill = document.getElementById('trading-utilization-fill');
        if (fill) {
            fill.style.width = Math.min(investedPct, 100) + '%';
            fill.className = 'utilization-fill' + (util.over_limit ? ' over-limit' : '');
        }

        var limitLine = document.getElementById('trading-utilization-limit');
        if (limitLine) {
            limitLine.style.left = limitPct + '%';
        }

        // Update labels
        var investedLabel = document.getElementById('trading-invested-label');
        if (investedLabel) {
            investedLabel.textContent = investedPct.toFixed(1) + '% invested';
        }

        var limitLabel = document.getElementById('trading-limit-label');
        if (limitLabel) {
            limitLabel.textContent = limitPct + '% limit';
        }

        // Update stats
        var investedEl = document.getElementById('trading-regime-invested');
        if (investedEl) {
            investedEl.textContent = '$' + (util.invested_usd || 0).toLocaleString();
        }

        var headroomEl = document.getElementById('trading-regime-headroom');
        if (headroomEl) {
            headroomEl.textContent = (util.headroom_pct || 0).toFixed(1) + '%';
            headroomEl.className = 'regime-stat-value' + (util.over_limit ? ' negative' : ' positive');
        }

        // Update per-asset count
        var durationEl = document.getElementById('trading-regime-duration');
        if (durationEl) {
            var byAsset = data.by_asset || {};
            var assetCount = Object.keys(byAsset).length;
            durationEl.textContent = assetCount + ' assets';
        }
    } catch (e) {
        console.error('Trading regime data error:', e);
    }
}

function updateLiveTradesTable(trades) {
    var table = document.getElementById('live-trades-table');
    if (!table) return;

    table.replaceChildren();

    if (!trades || trades.length === 0) {
        var noData = document.createElement('div');
        noData.className = 'no-data';
        noData.textContent = 'No recent trades';
        table.appendChild(noData);
        return;
    }

    // Create header
    var header = document.createElement('div');
    header.className = 'table-header';
    ['Time', 'Symbol', 'Side', 'P&L', 'Status', 'Source'].forEach(function(col) {
        var span = document.createElement('span');
        span.className = 'col-' + col.toLowerCase();
        span.textContent = col;
        header.appendChild(span);
    });
    table.appendChild(header);

    // Create rows
    trades.forEach(function(t) {
        var row = document.createElement('div');
        row.className = 'table-row';

        var timeCol = document.createElement('span');
        timeCol.className = 'col-time';
        timeCol.textContent = t.entry_time ? formatTime(t.entry_time) : '--';
        row.appendChild(timeCol);

        var symbolCol = document.createElement('span');
        symbolCol.className = 'col-symbol';
        symbolCol.textContent = t.symbol;
        row.appendChild(symbolCol);

        var sideCol = document.createElement('span');
        sideCol.className = 'col-side ' + t.side.toLowerCase();
        sideCol.textContent = t.side;
        row.appendChild(sideCol);

        var pnlCol = document.createElement('span');
        var pnlClass = (t.pnl_pct || 0) >= 0 ? 'green' : 'red';
        pnlCol.className = 'col-pnl ' + pnlClass;
        pnlCol.textContent = t.pnl_pct ? (t.pnl_pct >= 0 ? '+' : '') + t.pnl_pct.toFixed(2) + '%' : '--';
        row.appendChild(pnlCol);

        var statusCol = document.createElement('span');
        statusCol.className = 'col-status';
        statusCol.textContent = t.status;
        row.appendChild(statusCol);

        var sourceCol = document.createElement('span');
        sourceCol.className = 'col-source';
        sourceCol.textContent = t.source || 'unknown';
        row.appendChild(sourceCol);

        table.appendChild(row);
    });
}
