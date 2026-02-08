async function fetchData() {
    try {
        const response = await fetch('/api/system/info');
        const result = await response.json();
        if (result.success) {
            renderStats(result.data);
            renderTools(result.data.tools);
            renderDomains(result.data.plugins);
        }
    } catch (error) {
        console.error("Error:", error);
    }
}

function renderStats(data) {
    const bar = document.getElementById('stats-bar');
    const toolCount = Object.keys(data.tools).length;
    const pluginCount = Object.keys(data.plugins).length;
    const domainSet = new Set(Object.values(data.plugins).map(p => p.domain).filter(Boolean));

    bar.innerHTML = `
        <div class="stat">
            <span class="stat-value">${toolCount}</span>
            <span class="stat-label">Tools</span>
        </div>
        <div class="stat">
            <span class="stat-value">${pluginCount}</span>
            <span class="stat-label">Plugins</span>
        </div>
        <div class="stat">
            <span class="stat-value">${domainSet.size}</span>
            <span class="stat-label">Dominios</span>
        </div>
    `;
}

function renderTools(tools) {
    const grid = document.getElementById('tools-grid');
    grid.innerHTML = '';

    Object.entries(tools).forEach(([name, info]) => {
        const isOk = info.status === 'OK';
        const card = document.createElement('div');
        card.className = 'tool-card';
        card.innerHTML = `
            <div class="tool-header">
                <span class="tool-name">${name}</span>
                <span class="status-dot ${isOk ? '' : 'fail'}"></span>
            </div>
            <div class="tool-desc">${info.message || 'Herramienta operativa.'}</div>
        `;
        grid.appendChild(card);
    });
}

function renderDomains(plugins) {
    const container = document.getElementById('domains-container');
    container.innerHTML = '';

    // Group plugins by domain
    const domainMap = {};
    Object.entries(plugins).forEach(([name, info]) => {
        const domain = info.domain || 'global';
        if (!domainMap[domain]) domainMap[domain] = [];
        domainMap[domain].push({ name, ...info });
    });

    // Create accordion for each domain
    Object.entries(domainMap).forEach(([domain, pluginList]) => {
        const card = document.createElement('div');
        card.className = 'domain-card';

        const pluginsHTML = pluginList.map(p => {
            const depsHTML = p.dependencies.map(d =>
                `<span class="dep-tag">${d}</span>`
            ).join('');

            return `
                <div class="plugin-item">
                    <div class="plugin-name">${p.name}</div>
                    <div class="plugin-deps">
                        <span class="dep-arrow">⟵ uses:</span>
                        ${depsHTML || '<span class="dep-none">ninguna</span>'}
                    </div>
                </div>
            `;
        }).join('');

        card.innerHTML = `
            <div class="domain-header">
                <span class="domain-name">${domain}</span>
                <span class="domain-toggle">▼</span>
            </div>
            <div class="domain-content">
                <div class="plugins-list">
                    ${pluginsHTML}
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    // Open first domain by default
    const first = container.querySelector('.domain-card');
    if (first) first.classList.add('open');
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Event delegation for domain toggling
    const domainsContainer = document.getElementById('domains-container');
    if (domainsContainer) {
        domainsContainer.addEventListener('click', function(e) {
            const header = e.target.closest('.domain-header');
            if (header) {
                header.parentElement.classList.toggle('open');
            }
        });
    }

    fetchData();
    setInterval(fetchData, 10000);
});
