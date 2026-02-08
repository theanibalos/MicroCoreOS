let ws = null;
let systemData = { tools: {}, plugins: {}, domains: {} };

// === WEBSOCKET CONNECTION ===
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/events`);

    ws.onopen = () => {
        document.getElementById('ws-dot').classList.add('connected');
        document.getElementById('ws-label').textContent = 'En Vivo';
    };

    ws.onclose = () => {
        document.getElementById('ws-dot').classList.remove('connected');
        document.getElementById('ws-label').textContent = 'Desconectado';
        setTimeout(connectWebSocket, 3000); // Reconectar
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleEvent(data);
    };
}

// === EVENT HANDLER ===
function handleEvent(data) {
    const eventName = data.event;
    const payload = data.data?.payload || data.data || {};

    // Add to billboard
    addEventToBillboard(eventName, payload);

    // Special handling for logs
    if (eventName === 'system.log') {
        updateTicker(payload);
    }

    // Flash the corresponding building window
    flashBuildingWindow(eventName);
}

function addEventToBillboard(eventName, payload) {
    const list = document.getElementById('event-list');
    const item = document.createElement('div');

    let extraClass = '';
    if (eventName === 'system.log' && payload.level) {
        extraClass = `log-${payload.level}`;
    }

    item.className = `event-item ${extraClass}`;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'event-name';
    nameSpan.textContent = eventName;

    const timeSpan = document.createElement('span');
    timeSpan.className = 'event-time';
    timeSpan.textContent = new Date().toLocaleTimeString();

    const messageDiv = document.createElement('div');
    messageDiv.className = 'event-message';
    messageDiv.textContent = payload.message || JSON.stringify(payload).slice(0, 80);

    item.appendChild(nameSpan);
    item.appendChild(timeSpan);
    item.appendChild(messageDiv);

    list.insertBefore(item, list.firstChild);

    // Keep only last 20 events
    while (list.children.length > 20) {
        list.removeChild(list.lastChild);
    }
}

function updateTicker(logPayload) {
    const ticker = document.getElementById('ticker-content');
    const level = logPayload.level || 'INFO';
    const message = logPayload.message || '';

    ticker.innerHTML = '';
    const span = document.createElement('span');
    span.className = 'ticker-message';
    span.textContent = `[${level}] ${message}`;
    ticker.appendChild(span);
}

function flashBuildingWindow(eventName) {
    // Try to find a window related to this event
    const windows = document.querySelectorAll('.window');
    windows.forEach(w => {
        if (eventName.includes(w.dataset.domain)) {
            w.classList.add('active');
            setTimeout(() => w.classList.remove('active'), 1000);
        }
    });
}

// === RENDER TOWN ===
async function fetchAndRenderTown() {
    try {
        const response = await fetch('/api/system/info');
        const result = await response.json();

        if (result.success) {
            systemData = result.data;
            renderBuildings(systemData.plugins, systemData.domains);
            renderTools(systemData.tools);
        }
    } catch (error) {
        console.error("Error fetching system info:", error);
    }
}

function renderBuildings(plugins, domains) {
    const town = document.getElementById('town');
    town.innerHTML = '';

    // Group plugins by domain
    const domainMap = {};
    Object.entries(plugins).forEach(([name, info]) => {
        const domain = info.domain || 'global';
        if (!domainMap[domain]) domainMap[domain] = [];
        domainMap[domain].push(name);
    });

    // Create a building for each domain
    Object.entries(domainMap).forEach(([domain, pluginNames]) => {
        const building = document.createElement('div');
        building.className = 'building';

        const windowsHTML = pluginNames.map(p =>
            `<div class="window" data-domain="${domain}">${p.replace('Plugin', '')}</div>`
        ).join('');

        building.innerHTML = `
            <div class="building-structure">
                <div class="building-name">${domain}</div>
                <div class="building-windows">
                    ${windowsHTML}
                </div>
            </div>
        `;
        town.appendChild(building);
    });
}

function renderTools(tools) {
    const bar = document.getElementById('tools-bar');
    bar.innerHTML = '';

    Object.entries(tools).forEach(([name, info]) => {
        const isOk = info.status === 'OK';
        const icon = document.createElement('div');
        icon.className = 'tool-icon';
        icon.innerHTML = `
            <span class="dot ${isOk ? '' : 'fail'}"></span>
            ${name}
        `;
        bar.appendChild(icon);
    });
}

// === INIT ===
fetchAndRenderTown();
connectWebSocket();
setInterval(fetchAndRenderTown, 10000); // Refresh town every 10s
