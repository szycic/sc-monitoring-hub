// SC Monitoring Hub - Frontend SPA Application Engine
document.addEventListener('DOMContentLoaded', () => {
    let currentSystemId = 1;
    let pollTimer = null;
    let ws = null;
    let systems = [];
    let currentTabId = 'tab-dashboard';

    // Tab Navigation Elements
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    const systemSelect = document.getElementById('system-selector');

    initApp();

    function initApp() {
        setupTabs();
        setupEvents();
        loadSystems().then(() => {
            handleLocationRoute();
            startPolling();
        });
    }

    function setupTabs() {
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const targetTab = item.getAttribute('data-tab');
                const baseRoute = item.getAttribute('data-route') || 'dashboard';
                
                activateTab(targetTab, baseRoute);
            });
        });

        document.getElementById('btn-quick-htop').addEventListener('click', () => {
            activateTab('tab-htop', 'htop');
        });
        document.getElementById('btn-quick-journal').addEventListener('click', () => {
            activateTab('tab-journal', 'journal');
        });

        window.addEventListener('popstate', handleLocationRoute);
    }

    function activateTab(tabId, baseRoute = null) {
        currentTabId = tabId;
        const item = document.querySelector(`[data-tab="${tabId}"]`);
        if (!item) return;

        navItems.forEach(nav => nav.classList.remove('active'));
        tabContents.forEach(tab => tab.classList.remove('active'));

        item.classList.add('active');
        const targetSection = document.getElementById(tabId);
        if (targetSection) targetSection.classList.add('active');

        if (!baseRoute) {
            baseRoute = item.getAttribute('data-route') || 'dashboard';
        }

        const newPath = `/${baseRoute}`;
        if (window.location.pathname !== newPath) {
            history.pushState(null, '', newPath);
        }

        if (tabId === 'tab-htop') loadHtop();
        if (tabId === 'tab-journal') loadJournal();
        if (tabId === 'tab-systems') renderSystemsTab();
    }

    function handleLocationRoute() {
        const path = window.location.pathname;
        
        let tabId = 'tab-dashboard';
        let routeName = 'dashboard';

        if (path.startsWith('/systems')) {
            tabId = 'tab-systems';
            routeName = 'systems';
        } else if (path.startsWith('/htop')) {
            tabId = 'tab-htop';
            routeName = 'htop';
        } else if (path.startsWith('/journal')) {
            tabId = 'tab-journal';
            routeName = 'journal';
        } else {
            tabId = 'tab-dashboard';
            routeName = 'dashboard';
        }

        activateTab(tabId, routeName);
    }

    function setupEvents() {
        // Mobile drawer navigation handlers
        const mobileMenuBtn = document.getElementById('mobile-menu-btn');
        const sidebarDrawer = document.getElementById('sidebar-drawer');
        const sidebarOverlay = document.getElementById('sidebar-overlay');

        if (mobileMenuBtn && sidebarDrawer && sidebarOverlay) {
            const closeMobileMenu = () => {
                sidebarDrawer.classList.remove('open');
                sidebarOverlay.classList.remove('active');
            };

            mobileMenuBtn.addEventListener('click', () => {
                sidebarDrawer.classList.toggle('open');
                sidebarOverlay.classList.toggle('active');
            });

            sidebarOverlay.addEventListener('click', closeMobileMenu);

            navItems.forEach(item => {
                item.addEventListener('click', closeMobileMenu);
            });
        }

        systemSelect.addEventListener('change', (e) => {
            currentSystemId = parseInt(e.target.value);
            connectWebSocket();
            fetchCurrentSystemMetrics();
        });

        document.getElementById('btn-refresh').addEventListener('click', () => {
            fetchCurrentSystemMetrics();
        });

        // HTOP events
        document.getElementById('htop-search').addEventListener('input', debounce(loadHtop, 300));
        document.getElementById('htop-sort').addEventListener('change', loadHtop);
        document.getElementById('btn-refresh-htop').addEventListener('click', loadHtop);

        // Journal events
        document.getElementById('journal-search').addEventListener('input', debounce(loadJournal, 300));
        document.getElementById('journal-unit').addEventListener('input', debounce(loadJournal, 300));
        document.getElementById('journal-priority').addEventListener('change', loadJournal);
        document.getElementById('btn-refresh-journal').addEventListener('click', loadJournal);

        // Modal events
        const modal = document.getElementById('add-system-modal');
        const openModalBtns = [
            document.getElementById('btn-add-system-modal'),
            document.getElementById('btn-add-system-systems-tab')
        ];
        openModalBtns.forEach(btn => {
            if (btn) btn.addEventListener('click', () => modal.classList.add('active'));
        });
        document.getElementById('modal-close-btn').addEventListener('click', () => modal.classList.remove('active'));

        document.getElementById('btn-test-ssh').addEventListener('click', testSshConnection);
        document.getElementById('add-system-form').addEventListener('submit', handleAddSystemSubmit);
    }

    async function loadSystems() {
        try {
            const res = await fetch('/api/v1/systems');
            systems = await res.json();
            
            systemSelect.innerHTML = '';
            systems.forEach(sys => {
                const opt = document.createElement('option');
                opt.value = sys.id;
                const modeLabel = sys.is_local ? 'Local' : (sys.mode === 'agent' ? 'Agent' : 'Agentless');
                opt.textContent = `${sys.name} [${modeLabel}]`;
                systemSelect.appendChild(opt);
            });

            if (systems.length > 0 && !systems.some(s => s.id === currentSystemId)) {
                currentSystemId = systems[0].id;
                systemSelect.value = currentSystemId;
            } else if (currentSystemId) {
                systemSelect.value = currentSystemId;
            }

            renderSystemsTab();
            fetchCurrentSystemMetrics();
        } catch (err) {
            console.error('Failed to load systems:', err);
        }
    }

    function connectWebSocket() {
        if (!currentSystemId) return;
        if (ws) {
            try { ws.close(); } catch(e) {}
        }
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/api/v1/systems/${currentSystemId}/live`;
        
        ws = new WebSocket(wsUrl);
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                renderMetrics(data);
            } catch (e) {}
        };
        ws.onclose = () => {
            setTimeout(() => {
                if (currentSystemId) connectWebSocket();
            }, 4000);
        };
    }

    async function fetchCurrentSystemMetrics() {
        if (!currentSystemId) return;
        try {
            const res = await fetch(`/api/v1/systems/${currentSystemId}/metrics`);
            const data = await res.json();
            renderMetrics(data);
        } catch (err) {
            console.error('Failed to fetch metrics:', err);
        }
    }

    function renderMetrics(metrics) {
        if (!metrics) return;

        // CPU
        const cpuPct = metrics.cpu_percent || 0.0;
        document.getElementById('val-cpu').textContent = `${cpuPct.toFixed(1)}%`;
        document.getElementById('bar-cpu').style.width = `${Math.min(cpuPct, 100)}%`;
        document.getElementById('sub-cpu-cores').textContent = `${metrics.cpu_cores || 1} Core(s)`;

        // RAM
        const ramPct = metrics.memory_percent || 0.0;
        document.getElementById('val-ram').textContent = `${ramPct.toFixed(1)}%`;
        document.getElementById('bar-ram').style.width = `${Math.min(ramPct, 100)}%`;
        const ramUsedMb = Math.round((metrics.memory_used_bytes || 0) / (1024 * 1024));
        const ramTotMb = Math.round((metrics.memory_total_bytes || 0) / (1024 * 1024));
        document.getElementById('sub-ram-detail').textContent = `${ramUsedMb} MB / ${ramTotMb} MB`;

        // Disk
        const diskPct = metrics.disk_percent || 0.0;
        document.getElementById('val-disk').textContent = `${diskPct.toFixed(1)}%`;
        document.getElementById('bar-disk').style.width = `${Math.min(diskPct, 100)}%`;
        const diskUsedGb = ((metrics.disk_used_bytes || 0) / (1024 * 1024 * 1024)).toFixed(1);
        const diskTotGb = ((metrics.disk_total_bytes || 0) / (1024 * 1024 * 1024)).toFixed(1);
        document.getElementById('sub-disk-detail').textContent = `${diskUsedGb} GB / ${diskTotGb} GB`;

        // Uptime & Load
        const uptimeSec = metrics.uptime_seconds || 0;
        const days = Math.floor(uptimeSec / 86400);
        const hrs = Math.floor((uptimeSec % 86400) / 3600);
        const mins = Math.floor((uptimeSec % 3600) / 60);
        
        let uptimeStr = '';
        if (days > 0) {
            uptimeStr = `${days}d ${hrs}h ${mins}m`;
        } else if (hrs > 0) {
            uptimeStr = `${hrs}h ${mins}m`;
        } else {
            uptimeStr = `${mins}m`;
        }
        document.getElementById('val-uptime').textContent = uptimeStr;

        const loads = metrics.load_avg || [0, 0, 0];
        document.getElementById('sub-load-avg').textContent = `Load Avg: ${loads[0]}, ${loads[1]}, ${loads[2]}`;

        // System overview
        document.getElementById('info-hostname').textContent = metrics.hostname || '-';
        document.getElementById('info-platform').textContent = metrics.platform || '-';
        
        const sys = systems.find(s => s.id === currentSystemId);
        let modeText = sys ? (sys.is_local ? 'Local System' : (sys.mode === 'agent' ? 'Dedicated Agent' : 'Agentless Direct SSH')) : '-';
        if (metrics.agent_version) {
            modeText += ` (v${metrics.agent_version})`;
        }
        document.getElementById('info-mode').textContent = modeText;

        const txMb = ((metrics.net_bytes_sent || 0) / (1024 * 1024)).toFixed(1);
        const rxMb = ((metrics.net_bytes_recv || 0) / (1024 * 1024)).toFixed(1);
        document.getElementById('info-network').textContent = `TX: ${txMb} MB / RX: ${rxMb} MB`;
    }

    async function loadHtop() {
        if (!currentSystemId) return;
        const search = document.getElementById('htop-search').value;
        const sortBy = document.getElementById('htop-sort').value;

        try {
            const res = await fetch(`/api/v1/systems/${currentSystemId}/htop?search=${encodeURIComponent(search)}&sort_by=${sortBy}`);
            const procs = await res.json();
            renderHtopTable(procs);
        } catch (err) {
            console.error('Failed to fetch htop:', err);
        }
    }

    function renderHtopTable(procs) {
        const tbody = document.getElementById('htop-rows');
        document.getElementById('htop-count').textContent = `${procs.length} processes`;
        tbody.innerHTML = '';

        if (procs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No processes found matching criteria</td></tr>';
            return;
        }

        procs.forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="badge-pid">${p.pid}</td>
                <td style="color: var(--text-secondary);">${p.user}</td>
                <td class="badge-cpu">${p.cpu_percent}%</td>
                <td>${p.mem_percent}%</td>
                <td>${p.mem_mb} MB</td>
                <td style="word-break: break-all; max-width: 300px;">${escapeHtml(p.cmd)}</td>
                <td>
                    <button class="btn btn-danger btn-kill-proc" data-pid="${p.pid}" style="padding: 4px 8px; font-size: 0.75rem;">Kill</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        document.querySelectorAll('.btn-kill-proc').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const pid = e.target.getAttribute('data-pid');
                if (confirm(`Are you sure you want to terminate PID ${pid}?`)) {
                    await fetch(`/api/v1/systems/${currentSystemId}/process/kill`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pid: parseInt(pid) })
                    });
                    loadHtop();
                }
            });
        });
    }

    async function loadJournal() {
        if (!currentSystemId) return;
        const search = document.getElementById('journal-search').value;
        const unit = document.getElementById('journal-unit').value;
        const priority = document.getElementById('journal-priority').value;

        try {
            const res = await fetch(`/api/v1/systems/${currentSystemId}/journalctl?search=${encodeURIComponent(search)}&unit=${encodeURIComponent(unit)}&priority=${priority}`);
            const logs = await res.json();
            renderJournalConsole(logs);
        } catch (err) {
            console.error('Failed to fetch logs:', err);
        }
    }

    function renderJournalConsole(logs) {
        const consoleEl = document.getElementById('journal-console');
        consoleEl.innerHTML = '';

        if (logs.length === 0) {
            consoleEl.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">No journalctl logs available matching query</div>';
            return;
        }

        logs.forEach(l => {
            const line = document.createElement('div');
            line.className = 'log-line';
            line.innerHTML = `
                <span class="log-ts">${l.timestamp || '00:00:00'}</span>
                <span class="log-unit">${escapeHtml(l.unit || 'system')}</span>
                <span class="log-prio ${l.priority}">${l.priority}</span>
                <span class="log-msg">${escapeHtml(l.message)}</span>
            `;
            consoleEl.appendChild(line);
        });
        consoleEl.scrollTop = consoleEl.scrollHeight;
    }

    function renderSystemsTab() {
        const container = document.getElementById('systems-list-container');
        container.innerHTML = '';

        systems.forEach(sys => {
            const card = document.createElement('div');
            card.className = 'metric-card';
            card.style.flexDirection = 'column';
            card.style.alignItems = 'stretch';
            
            const modeBadge = sys.is_local ? 'Local System' : (sys.mode === 'agent' ? 'Dedicated Agent' : 'Agentless SSH');
            const agentVerBadge = sys.mode === 'agent' ? '<span style="margin-left: 8px; font-size: 0.75rem; background: rgba(6, 182, 212, 0.15); color: var(--accent-cyan); padding: 2px 6px; border-radius: 4px; font-weight: 600;">v1.0.2</span>' : '';
            
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="font-weight: 600; font-size: 1.05rem;">${escapeHtml(sys.name)}</div>
                    <span class="status-indicator ${sys.status === 'online' ? 'online' : 'offline'}"></span>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
                    Host: <span style="color: var(--text-primary); font-family: var(--font-mono);">${sys.host}:${sys.port || 0}</span>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 16px;">
                    Mode: <span style="color: var(--accent-cyan); font-weight: 600;">${modeBadge}</span>${agentVerBadge}
                </div>
                <div style="display: flex; gap: 10px; margin-top: auto;">
                    ${!sys.is_local ? `
                        ${sys.mode === 'agentless' ? `
                            <button class="btn btn-secondary btn-deploy-agent" data-id="${sys.id}" style="font-size: 0.8rem; flex: 1; justify-content: center;">Deploy Agent</button>
                        ` : `
                            <button class="btn btn-secondary btn-uninstall-agent" data-id="${sys.id}" style="font-size: 0.8rem; flex: 1; justify-content: center;">Uninstall Agent</button>
                        `}
                        <button class="btn btn-danger btn-delete-sys" data-id="${sys.id}" style="font-size: 0.8rem; flex: 1; justify-content: center;">Delete</button>
                    ` : '<span style="font-size: 0.8rem; color: var(--text-muted);">Primary Hub Host</span>'}
                </div>
            `;
            container.appendChild(card);
        });

        document.querySelectorAll('.btn-deploy-agent').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.getAttribute('data-id');
                btn.disabled = true;
                btn.textContent = 'Deploying...';
                const res = await fetch(`/api/v1/systems/${id}/deploy-agent`, { method: 'POST' });
                const result = await res.json();
                alert(result.message || result.error);
                loadSystems();
            });
        });

        document.querySelectorAll('.btn-uninstall-agent').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.getAttribute('data-id');
                btn.disabled = true;
                btn.textContent = 'Uninstalling...';
                const res = await fetch(`/api/v1/systems/${id}/uninstall-agent`, { method: 'POST' });
                const result = await res.json();
                alert(result.message || result.error);
                loadSystems();
            });
        });

        document.querySelectorAll('.btn-delete-sys').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.getAttribute('data-id');
                if (confirm('Delete this system from monitoring hub?')) {
                    await fetch(`/api/v1/systems/${id}`, { method: 'DELETE' });
                    loadSystems();
                }
            });
        });
    }

    async function testSshConnection() {
        const output = document.getElementById('modal-terminal-output');
        output.style.display = 'block';
        output.textContent = 'Testing SSH connection...';

        const payload = {
            host: document.getElementById('system-host').value,
            port: parseInt(document.getElementById('system-port').value),
            username: document.getElementById('system-user').value,
            auth_type: document.getElementById('system-auth-type').value,
            auth_credential: document.getElementById('system-auth-cred').value
        };

        try {
            const res = await fetch('/api/v1/systems/test-ssh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            output.textContent = data.message || data.error;
        } catch (err) {
            output.textContent = 'Connection test failed: ' + err;
        }
    }

    async function handleAddSystemSubmit(e) {
        e.preventDefault();
        const btnSave = document.getElementById('btn-save-system');
        const origText = btnSave ? btnSave.textContent : 'Save & Add System';
        if (btnSave) {
            btnSave.disabled = true;
            btnSave.textContent = 'Adding System...';
        }

        const payload = {
            name: document.getElementById('system-name').value,
            host: document.getElementById('system-host').value,
            port: parseInt(document.getElementById('system-port').value),
            username: document.getElementById('system-user').value,
            auth_type: document.getElementById('system-auth-type').value,
            auth_credential: document.getElementById('system-auth-cred').value,
            mode: document.getElementById('system-mode').value
        };

        try {
            const res = await fetch('/api/v1/systems', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                document.getElementById('add-system-modal').classList.remove('active');
                document.getElementById('add-system-form').reset();
                const output = document.getElementById('modal-terminal-output');
                if (output) output.style.display = 'none';
                loadSystems();
            } else {
                const errData = await res.json();
                alert('Error adding system: ' + (errData.detail || errData.error));
            }
        } catch (err) {
            alert('Failed to add system: ' + err);
        } finally {
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.textContent = origText;
            }
        }
    }

    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(() => {
            fetchCurrentSystemMetrics();
        }, 4000);
    }

    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
});
