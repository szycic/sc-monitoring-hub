import psutil
import time
import os
import platform
import subprocess
from typing import Dict, Any, List

def get_local_metrics() -> Dict[str, Any]:
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time

    cpu_pct = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()

    try:
        load_avg = list(os.getloadavg())
    except Exception:
        load_avg = [0.0, 0.0, 0.0]

    return {
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": cpu_pct,
        "cpu_cores": psutil.cpu_count(logical=True),
        "cpu_per_core": cpu_per_core,
        "memory_percent": mem.percent,
        "memory_used_bytes": mem.used,
        "memory_total_bytes": mem.total,
        "swap_percent": swap.percent,
        "swap_used_bytes": swap.used,
        "swap_total_bytes": swap.total,
        "disk_percent": disk.percent,
        "disk_used_bytes": disk.used,
        "disk_total_bytes": disk.total,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "uptime_seconds": round(uptime, 1),
        "load_avg": load_avg,
        "timestamp": time.time()
    }

def get_local_processes(search: str = "", limit: int = 100, sort_by: str = "cpu_percent") -> List[Dict[str, Any]]:
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
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    reverse = True
    if sort_by in ["pid", "name"]:
        reverse = False

    procs.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)
    return procs[:limit]

def get_local_journal(unit: str = "", priority: str = "", lines: int = 100, search: str = "") -> List[Dict[str, Any]]:
    cmd = ["journalctl", "-n", str(lines), "-o", "json"]
    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            # Fallback to standard journalctl without json if json fails
            cmd_simple = ["journalctl", "-n", str(lines), "--no-pager"]
            if unit:
                cmd_simple.extend(["-u", unit])
            res_simple = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=5)
            output_lines = res_simple.stdout.strip().split("\n") if res_simple.stdout else []
            logs = []
            for l in output_lines:
                if search and search.lower() not in l.lower():
                    continue
                logs.append({
                    "timestamp": "",
                    "unit": unit or "system",
                    "priority": "INFO",
                    "message": l
                })
            return logs

        import json
        logs = []
        for line in res.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                msg = data.get("MESSAGE", "")
                if isinstance(msg, list):
                    msg = " ".join([str(m) for m in msg])
                else:
                    msg = str(msg)

                if search and search.lower() not in msg.lower():
                    continue

                ts_us = int(data.get("__REALTIME_TIMESTAMP", 0))
                ts_str = time.strftime("%b %d %H:%M:%S", time.localtime(ts_us / 1000000)) if ts_us else ""
                unit_name = data.get("_SYSTEMD_UNIT") or data.get("SYSLOG_IDENTIFIER") or "system"
                prio_code = int(data.get("PRIORITY", 6))
                
                prio_map = {0: "EMERG", 1: "ALERT", 2: "CRIT", 3: "ERR", 4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG"}
                prio_str = prio_map.get(prio_code, "INFO")

                logs.append({
                    "timestamp": ts_str,
                    "unit": unit_name,
                    "priority": prio_str,
                    "message": msg
                })
            except Exception:
                continue

        return logs
    except Exception as e:
        return [{"timestamp": "", "unit": "error", "priority": "ERR", "message": f"Failed to read journalctl: {str(e)}"}]

def kill_local_process(pid: int, signal_num: int = 9) -> bool:
    try:
        p = psutil.Process(pid)
        p.send_signal(signal_num)
        return True
    except Exception:
        return False
