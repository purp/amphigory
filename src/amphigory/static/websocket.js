/**
 * Amphigory WebSocket Client
 *
 * Handles real-time updates from the daemon via the webapp's WebSocket endpoint.
 */

class AmphigoryWebSocket {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.handlers = {
            'daemon_config': [],
            'disc_event': [],
            'progress': [],
            'heartbeat': [],
            'sync': [],
        };

        // UI elements
        this.statusIndicator = null;
        this.discInfo = null;
    }

    /**
     * Initialize the WebSocket connection
     */
    init() {
        this.statusIndicator = document.getElementById('daemon-status');
        this.discInfo = document.getElementById('disc-info');

        // Fetch initial daemon status
        this.fetchDaemonStatus();

        this.connect();

        // Register default handlers
        this.on('daemon_config', (data) => this.handleDaemonConfig(data));
        this.on('disc_event', (data) => this.handleDiscEvent(data));
        this.on('progress', (data) => this.handleProgress(data));
        this.on('heartbeat', (data) => this.handleHeartbeat(data));
    }

    /**
     * Fetch daemon status from API
     */
    async fetchDaemonStatus() {
        try {
            const response = await fetch('/api/settings/daemons');
            const data = await response.json();
            const daemonCount = data.daemons ? data.daemons.length : 0;
            this.updateDaemonStatus(daemonCount > 0, daemonCount);
        } catch (error) {
            console.error('Failed to fetch daemon status:', error);
        }
    }

    /**
     * Connect to the WebSocket endpoint
     */
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.reconnectAttempts = 0;
                // Refresh daemon status when reconnected
                this.fetchDaemonStatus();
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };

            this.ws.onmessage = (event) => {
                this.handleMessage(event.data);
            };
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.scheduleReconnect();
        }
    }

    /**
     * Schedule a reconnection attempt
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => this.connect(), delay);
    }

    /**
     * Handle incoming WebSocket message
     */
    handleMessage(data) {
        try {
            const message = JSON.parse(data);
            const type = message.type;

            if (this.handlers[type]) {
                this.handlers[type].forEach(handler => handler(message));
            }
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    }

    /**
     * Register a message handler
     */
    on(type, handler) {
        if (!this.handlers[type]) {
            this.handlers[type] = [];
        }
        this.handlers[type].push(handler);
    }

    /**
     * Send a message through the WebSocket
     */
    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }

    /**
     * Update the daemon status indicator based on actual daemon connections
     */
    updateDaemonStatus(connected, count = 0) {
        if (!this.statusIndicator) return;

        if (connected) {
            this.statusIndicator.className = 'daemon-status status-connected';
            const text = count === 1 ? 'Daemon Connected' : `${count} Daemons Connected`;
            this.statusIndicator.textContent = text;
            this.statusIndicator.title = text;
        } else {
            this.statusIndicator.className = 'daemon-status status-disconnected';
            this.statusIndicator.textContent = 'No Daemon';
            this.statusIndicator.title = 'No daemon connected';
        }
    }

    /**
     * Handle daemon_config message (daemon connected to webapp)
     */
    handleDaemonConfig(data) {
        console.log('Daemon registered:', data.daemon_id);
        // Refresh daemon status from API to get accurate count
        this.fetchDaemonStatus();
        this.updateDaemonInfo(data);
    }

    /**
     * Handle disc_event message (insert/eject)
     */
    handleDiscEvent(data) {
        console.log('Disc event:', data.event, data.device);

        if (!this.discInfo) return;

        if (data.event === 'inserted') {
            this.discInfo.innerHTML = `
                <p class="status-message disc-inserted">
                    Disc inserted: ${data.volume_name || 'Unknown'}
                </p>
                <p class="status-detail">Device: ${data.device}</p>
            `;
        } else if (data.event === 'ejected') {
            this.discInfo.innerHTML = `
                <p class="status-message">No disc detected</p>
            `;
        }
    }

    /**
     * Handle progress update
     */
    handleProgress(data) {
        // Dispatch a custom event for progress updates
        const event = new CustomEvent('amphigory:progress', { detail: data });
        document.dispatchEvent(event);

        // Update progress bar if exists
        const progressBar = document.getElementById(`progress-${data.task_id}`);
        if (progressBar) {
            progressBar.style.width = `${data.percent}%`;
            progressBar.textContent = `${data.percent}%`;
        }
    }

    /**
     * Handle heartbeat
     */
    handleHeartbeat(data) {
        // Update last-seen timestamp
        this.lastHeartbeat = new Date();
    }

    /**
     * Update daemon info display
     */
    updateDaemonInfo(data) {
        const daemonList = document.getElementById('connected-daemons');
        if (!daemonList) return;

        // This will be used by the settings page
        const event = new CustomEvent('amphigory:daemon_connected', { detail: data });
        document.dispatchEvent(event);
    }
}

// Create global instance
window.amphigoryWS = new AmphigoryWebSocket();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.amphigoryWS.init();
});
