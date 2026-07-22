import hashlib

AGENT_VERSION = "1.0.2"

AGENT_PYTHON_SCRIPT = '''#!/usr/bin/env python3
"""
SC Monitoring Agent
Standalone lightweight agent for sc-monitoring-hub
"""
import os
import sys
import time
import json
import platform
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

AGENT_VERSION = "1.0.2"

try:
    import psutil
except ImportError:
    psutil = None

PORT = int(os.environ.get("AGENT_PORT", 9990))

def get_metrics():
    if psutil:
        boot_time = psutil.boot_time()
        uptime = time.time() - boot_time
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        
        mem_pct, mem_used, mem_tot = mem.percent, mem.used, mem.total
        swap_pct, swap_used, swap_tot = swap.percent, swap.used, swap.total
        disk_pct, disk_used, disk_tot = disk.percent, disk.used, disk.total
        sent, recv = net.bytes_sent, net.bytes_recv
        cores = psutil.cpu_count(logical=True)
    else:
        uptime = float(open('/proc/uptime').read().split()[0]) if os.path.exists('/proc/uptime') else 0.0
        cpu_pct = 0.0
        cpu_per_core = []
        mem_pct, mem_used, mem_tot = 0.0, 0, 0
        swap_pct, swap_used, swap_tot = 0.0, 0, 0
        disk_pct, disk_used, disk_tot = 0.0, 0, 0
        sent, recv = 0, 0
        cores = 1

    try:
        load_avg = list(os.getloadavg())
    except Exception:
        load_avg = [0.0, 0.0, 0.0]

    return {
        "agent_version": AGENT_VERSION,
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": cpu_pct,
        "cpu_cores": cores,
        "cpu_per_core": cpu_per_core,
        "memory_percent": mem_pct,
        "memory_used_bytes": mem_used,
        "memory_total_bytes": mem_tot,
        "swap_percent": swap_pct,
        "swap_used_bytes": swap_used,
        "swap_total_bytes": swap_tot,
        "disk_percent": disk_pct,
        "disk_used_bytes": disk_used,
        "disk_total_bytes": disk_tot,
        "net_bytes_sent": sent,
        "net_bytes_recv": recv,
        "uptime_seconds": round(uptime, 1),
        "load_avg": load_avg,
        "timestamp": time.time()
    }

def get_processes(search="", limit=100, sort_by="cpu_percent"):
    if not psutil:
        return []
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'username', 'status', 'cpu_percent', 'memory_percent', 'memory_info', 'cmdline']):
        try:
            info = p.info
            cmd = " ".join(info['cmdline']) if info['cmdline'] else info['name'] or ""
            if search and search.lower() not in cmd.lower() and search.lower() not in (info['name'] or "").lower() and search not in str(info['pid']):
                continue
            mem_mb = round((info['memory_info'].rss / (1024 * 1024)), 1) if info['memory_info'] else 0.0
            procs.append({
                "pid": info['pid'],
                "name": info['name'] or f"PID {info['pid']}",
                "user": info['username'] or "unknown",
                "status": info['status'] or "R",
                "cpu_percent": round(info['cpu_percent'] or 0.0, 1),
                "mem_percent": round(info['memory_percent'] or 0.0, 1),
                "mem_mb": mem_mb,
                "cmd": cmd
            })
        except Exception:
            continue
    reverse = True
    if sort_by in ["pid", "name"]:
        reverse = False
    procs.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)
    return procs[:limit]

def get_journal(unit="", priority="", lines=100, search=""):
    cmd = ["journalctl", "-n", str(lines), "-o", "json"]
    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return []
        logs = []
        for line in res.stdout.strip().split("\\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                msg = str(data.get("MESSAGE", ""))
                if search and search.lower() not in msg.lower():
                    continue
                ts_us = int(data.get("__REALTIME_TIMESTAMP", 0))
                ts_str = time.strftime("%b %d %H:%M:%S", time.localtime(ts_us / 1000000)) if ts_us else ""
                unit_name = data.get("_SYSTEMD_UNIT") or data.get("SYSLOG_IDENTIFIER") or "system"
                prio_code = int(data.get("PRIORITY", 6))
                prio_map = {0: "EMERG", 1: "ALERT", 2: "CRIT", 3: "ERR", 4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG"}
                logs.append({
                    "timestamp": ts_str,
                    "unit": unit_name,
                    "priority": prio_map.get(prio_code, "INFO"),
                    "message": msg
                })
            except Exception:
                continue
        return logs
    except Exception:
        return []

class AgentHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({"status": "ok", "agent": "sc-monitoring-agent", "agent_version": AGENT_VERSION})
            return

        if path == "/metrics":
            self._send_json(get_metrics())
            return

        if path == "/htop":
            search = qs.get("search", [""])[0]
            limit = int(qs.get("limit", [100])[0])
            sort_by = qs.get("sort_by", ["cpu_percent"])[0]
            self._send_json(get_processes(search=search, limit=limit, sort_by=sort_by))
            return

        if path == "/journalctl":
            unit = qs.get("unit", [""])[0]
            priority = qs.get("priority", [""])[0]
            lines = int(qs.get("lines", [100])[0])
            search = qs.get("search", [""])[0]
            self._send_json(get_journal(unit=unit, priority=priority, lines=lines, search=search))
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/process/kill":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                pid = int(data.get("pid"))
                if psutil and psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    p.kill()
                    self._send_json({"success": True, "message": f"Killed PID {pid}"})
                else:
                    self._send_json({"success": False, "error": "PID not found"}, 400)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        self._send_json({"error": "Not Found"}, 404)

def run():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, AgentHandler)
    print(f"SC Monitoring Agent v{AGENT_VERSION} running on port {PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run()
'''

AGENT_SYSTEMD_SERVICE = '''[Unit]
Description=SC Monitoring Hub Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/sc-agent
ExecStart=/usr/bin/python3 /opt/sc-agent/sc_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
'''

def get_agent_hash() -> str:
    return hashlib.sha256(AGENT_PYTHON_SCRIPT.encode('utf-8')).hexdigest()[:12]
