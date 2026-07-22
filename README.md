# SC Monitoring Hub

This repository contains the source code for the `sc_monitoring_hub` package.

The app is a self-hosted FastAPI dashboard and monitoring controller for real-time system resource tracking, CPU/RAM/Disk metrics, `htop`-style process management, and `journalctl` log inspection across local and remote Linux machines over SSH.

It is intended for personal or local-network use and does not include production authentication by default. If you expose the app beyond a trusted LAN, add authentication, TLS, and restrict access to the API endpoints.

## Features

- **Auto-Registered Local Host**: Out-of-the-box monitoring for the primary machine running the hub using native OS APIs (`psutil`, `/proc`, `journalctl`).
- **Dual Monitoring Modes**:
  - **Agentless Direct SSH Mode (Default)**: Connects over SSH on demand to fetch system metrics, process tables, and journal logs without installing software on remote hosts.
  - **Dedicated Agent Mode (1-Click Install)**: Automatically uploads `sc_agent.py` and registers `sc-monitoring-agent.service` systemd daemon over SSH for sub-second streaming and offline buffering.
- **Automatic Agent Auto-Update**: Checks remote agent versions during polling cycles and automatically redeploys updated agent scripts over SSH whenever the hub's agent template is updated.
- **HTOP Process Manager**: Color-coded process table with CPU %, MEM %, user filtering, keyword search, column sorting, and process termination (Kill PID).
- **Journalctl Log Viewer**: Terminal-style log console with Fira Code font, priority color badges (`ERR`, `WARN`, `INFO`), systemd unit filter, and search.

## Environment Variables

The following environment variables can be set to configure the application:

| Variable | Purpose | Default |
|---|---|---|
| `DB_PATH` | Path to the SQLite database file | `./data/hub.db` |
| `POLL_INTERVAL_SECONDS` | Interval in seconds for background metric polling | `3.0` |
| `HOST` | Bind host address for the FastAPI server | `0.0.0.0` |
| `PORT` | Bind port for the FastAPI server | `8000` |

## Installation

To set up the virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
pip install -r requirements.txt
```

## Running

To start the monitoring hub application, run:

```bash
PYTHONPATH=src python -m uvicorn sc_monitoring_hub.main:app --host 0.0.0.0 --port 8000
```

Then open the dashboard in your browser at:
```text
http://127.0.0.1:8000
```

## API Endpoints

The hub exposes REST API endpoints under `/api/v1` versioned prefix:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/systems` | `GET` | List all monitored systems and their current status |
| `/api/v1/systems` | `POST` | Add a new remote system (SSH credentials / Mode) |
| `/api/v1/systems/{id}` | `DELETE` | Remove a monitored system |
| `/api/v1/systems/test-ssh` | `POST` | Test SSH connectivity and credentials |
| `/api/v1/systems/{id}/metrics` | `GET` | Fetch real-time system resource metrics |
| `/api/v1/systems/{id}/history` | `GET` | Fetch historical metric time-series data |
| `/api/v1/systems/{id}/htop` | `GET` | Fetch process table (supports `search`, `sort_by`, `limit`) |
| `/api/v1/systems/{id}/process/kill` | `POST` | Send kill signal to a PID |
| `/api/v1/systems/{id}/journalctl` | `GET` | Fetch system logs (supports `unit`, `priority`, `search`, `lines`) |
| `/api/v1/systems/{id}/deploy-agent` | `POST` | Automate deploying the `sc-monitoring-agent` systemd service over SSH |
| `/api/v1/systems/{id}/uninstall-agent` | `POST` | Stop and remove the agent service over SSH |
