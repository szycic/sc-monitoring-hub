import gc
import paramiko
import io
import json
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Tuple
from sc_monitoring_hub.agent_template import AGENT_PYTHON_SCRIPT, AGENT_SYSTEMD_SERVICE, AGENT_VERSION

# Global SSH Connection Pool
_SSH_POOL: Dict[int, paramiko.SSHClient] = {}

def _get_ssh_client(device: Dict[str, Any], timeout: int = 8) -> paramiko.SSHClient:
    device_id = device.get("id", 0)
    
    if device_id in _SSH_POOL:
        client = _SSH_POOL[device_id]
        transport = client.get_transport()
        if transport and transport.is_active():
            return client
        else:
            try:
                client.close()
            except Exception:
                pass
            _SSH_POOL.pop(device_id, None)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    host = device["host"]
    port = device["port"] or 22
    username = device["username"] or "root"
    auth_type = device.get("auth_type", "password")
    cred = device.get("auth_credential", "")

    kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": timeout,
        "banner_timeout": timeout
    }

    if auth_type == "password":
        kwargs["password"] = cred
    elif auth_type == "key_file":
        kwargs["key_filename"] = cred
    elif auth_type == "key_content":
        key_file_obj = io.StringIO(cred)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file_obj)
        except Exception:
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file_obj)
            except Exception:
                pkey = paramiko.PKey.from_private_key(key_file_obj)
        kwargs["pkey"] = pkey

    client.connect(**kwargs)
    if device_id:
        _SSH_POOL[device_id] = client
    return client

def close_ssh_connection(device_id: int):
    if device_id in _SSH_POOL:
        try:
            _SSH_POOL[device_id].close()
        except Exception:
            pass
        _SSH_POOL.pop(device_id, None)

def test_ssh_connection(host: str, port: int, username: str, auth_type: str, auth_credential: str) -> Tuple[bool, str]:
    dummy_device = {
        "id": 0,
        "host": host,
        "port": port,
        "username": username,
        "auth_type": auth_type,
        "auth_credential": auth_credential
    }
    try:
        client = _get_ssh_client(dummy_device, timeout=5)
        stdin, stdout, stderr = client.exec_command("hostname; uname -sr")
        out = stdout.read().decode('utf-8').strip()
        stdout.close()
        stderr.close()
        client.close()
        return True, f"Connected successfully: {out}"
    except Exception as e:
        return False, str(e)

def fetch_ssh_metrics(device: Dict[str, Any]) -> Dict[str, Any]:
    if device.get("mode") == "agent":
        agent_port = device.get("agent_port", 9990)
        url = f"http://{device['host']}:{agent_port}/metrics"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SC-Monitoring-Hub"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get("agent_version") != AGENT_VERSION:
                        # Auto-update outdated agent on remote target
                        success, _ = deploy_agent(device)
                        if success:
                            time.sleep(1)
                            try:
                                with urllib.request.urlopen(req, timeout=3) as new_resp:
                                    if new_resp.status == 200:
                                        return json.loads(new_resp.read().decode('utf-8'))
                            except Exception:
                                pass
                    return data
        except Exception:
            pass

    client = _get_ssh_client(device)
    py_cmd = (
        "python3 -c \"import os, time, platform, json; "
        "uptime = float(open('/proc/uptime').read().split()[0]) if os.path.exists('/proc/uptime') else 0.0; "
        "mem = open('/proc/meminfo').read() if os.path.exists('/proc/meminfo') else ''; "
        "lines = dict(l.split(':') for l in mem.splitlines() if ':' in l); "
        "total = int(lines.get('MemTotal', '0 kB').split()[0]) * 1024; "
        "free = int(lines.get('MemAvailable', lines.get('MemFree', '0 kB')).split()[0]) * 1024; "
        "used = total - free; "
        "mem_pct = round((used / total * 100), 1) if total else 0; "
        "load = list(os.getloadavg()) if hasattr(os, 'getloadavg') else [0,0,0]; "
        "d = os.statvfs('/') if hasattr(os, 'statvfs') else None; "
        "d_tot = (d.f_blocks * d.f_frsize) if d else 0; "
        "d_free = (d.f_bavail * d.f_frsize) if d else 0; "
        "d_used = d_tot - d_free; "
        "d_pct = round((d_used / d_tot * 100), 1) if d_tot else 0.0; "
        "print(json.dumps({'hostname': platform.node(), 'platform': f'{platform.system()} {platform.release()}', "
        "'cpu_percent': round(load[0]*10, 1), 'cpu_cores': os.cpu_count() or 1, 'memory_percent': mem_pct, "
        "'memory_used_bytes': used, 'memory_total_bytes': total, 'disk_percent': d_pct, "
        "'disk_used_bytes': d_used, 'disk_total_bytes': d_tot, 'load_avg': load, "
        "'uptime_seconds': round(uptime, 1), 'timestamp': time.time()}))\""
    )
    try:
        stdin, stdout, stderr = client.exec_command(py_cmd)
        out_str = stdout.read().decode('utf-8').strip()
        stdout.close()
        stderr.close()
    except Exception:
        close_ssh_connection(device.get("id", 0))
        raise

    if out_str:
        try:
            return json.loads(out_str)
        except Exception:
            pass

    return {
        "hostname": device.get("name", device["host"]),
        "platform": "Linux (SSH Agentless)",
        "cpu_percent": 0.0,
        "cpu_cores": 1,
        "memory_percent": 0.0,
        "memory_used_bytes": 0,
        "memory_total_bytes": 0,
        "disk_percent": 0.0,
        "disk_used_bytes": 0,
        "disk_total_bytes": 0,
        "load_avg": [0.0, 0.0, 0.0],
        "uptime_seconds": 0.0,
        "timestamp": time.time()
    }

def fetch_ssh_processes(device: Dict[str, Any], search: str = "", limit: int = 100, sort_by: str = "cpu_percent") -> List[Dict[str, Any]]:
    if device.get("mode") == "agent":
        agent_port = device.get("agent_port", 9990)
        params = urllib.parse.urlencode({"search": search, "limit": limit, "sort_by": sort_by})
        url = f"http://{device['host']}:{agent_port}/htop?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SC-Monitoring-Hub"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except Exception:
            pass

    client = _get_ssh_client(device)
    ps_cmd = "ps aux --sort=-%cpu | head -n 120"
    try:
        stdin, stdout, stderr = client.exec_command(ps_cmd)
        lines = stdout.read().decode('utf-8').strip().split('\n')
        stdout.close()
        stderr.close()
    except Exception:
        close_ssh_connection(device.get("id", 0))
        raise

    procs = []
    if len(lines) > 1:
        for line in lines[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                user, pid, cpu, mem, vsz, rss, tty, stat, start, time_str, cmd = parts
                try:
                    pid_int = int(pid)
                    cpu_f = float(cpu)
                    mem_f = float(mem)
                    rss_mb = round(int(rss) / 1024, 1)

                    if search and search.lower() not in cmd.lower() and search.lower() not in user.lower() and search not in pid:
                        continue

                    procs.append({
                        "pid": pid_int,
                        "name": cmd.split()[0].split('/')[-1] if cmd else "process",
                        "user": user,
                        "status": stat,
                        "cpu_percent": cpu_f,
                        "mem_percent": mem_f,
                        "mem_mb": rss_mb,
                        "cmd": cmd
                    })
                except ValueError:
                    continue

    reverse = True
    if sort_by in ["pid", "name"]:
        reverse = False
    procs.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)
    return procs[:limit]

def fetch_ssh_journal(device: Dict[str, Any], unit: str = "", priority: str = "", lines: int = 100, search: str = "") -> List[Dict[str, Any]]:
    if device.get("mode") == "agent":
        agent_port = device.get("agent_port", 9990)
        params = urllib.parse.urlencode({"unit": unit, "priority": priority, "lines": lines, "search": search})
        url = f"http://{device['host']}:{agent_port}/journalctl?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SC-Monitoring-Hub"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except Exception:
            pass

    client = _get_ssh_client(device)
    cmd = f"journalctl -n {lines} -o json"
    if unit:
        cmd += f" -u {unit}"
    if priority:
        cmd += f" -p {priority}"

    try:
        stdin, stdout, stderr = client.exec_command(cmd)
        out_str = stdout.read().decode('utf-8').strip()
        stdout.close()
        stderr.close()
    except Exception:
        close_ssh_connection(device.get("id", 0))
        raise

    logs = []
    for line in out_str.split("\n"):
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

def kill_ssh_process(device: Dict[str, Any], pid: int, signal_num: int = 9) -> bool:
    try:
        client = _get_ssh_client(device)
        stdin, stdout, stderr = client.exec_command(f"kill -{signal_num} {pid}")
        stdout.close()
        stderr.close()
        return True
    except Exception:
        close_ssh_connection(device.get("id", 0))
        return False

def deploy_agent(device: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        client = _get_ssh_client(device, timeout=12)
        sftp = client.open_sftp()
        
        tmp_agent = "/tmp/sc_agent.py"
        tmp_service = "/tmp/sc-monitoring-agent.service"
        
        f1 = sftp.file(tmp_agent, 'w')
        f1.write(AGENT_PYTHON_SCRIPT)
        f1.close()
        
        f2 = sftp.file(tmp_service, 'w')
        f2.write(AGENT_SYSTEMD_SERVICE)
        f2.close()
        sftp.close()

        install_cmd = (
            "sudo mkdir -p /opt/sc-agent && "
            "sudo cp /tmp/sc_agent.py /opt/sc-agent/sc_agent.py && "
            "sudo chmod +x /opt/sc-agent/sc_agent.py && "
            "sudo cp /tmp/sc-monitoring-agent.service /etc/systemd/system/sc-monitoring-agent.service && "
            "sudo systemctl daemon-reload && sudo systemctl enable --now sc-monitoring-agent && sudo systemctl restart sc-monitoring-agent"
        )
        stdin, stdout, stderr = client.exec_command(install_cmd)
        exit_code = stdout.channel.recv_exit_status()
        out_msg = stdout.read().decode('utf-8') + stderr.read().decode('utf-8')
        stdout.close()
        stderr.close()

        if exit_code != 0:
            user_cmd = (
                "mkdir -p ~/.local/share/sc-agent && "
                "cp /tmp/sc_agent.py ~/.local/share/sc-agent/sc_agent.py && "
                "chmod +x ~/.local/share/sc-agent/sc_agent.py && "
                "pkill -9 -f sc_agent.py || true; "
                "nohup python3 ~/.local/share/sc-agent/sc_agent.py >/dev/null 2>&1 &"
            )
            stdin, stdout, stderr = client.exec_command(user_cmd)
            stdout.channel.recv_exit_status()
            out_msg = "Agent started in user background process (~/.local/share/sc-agent)"
            stdout.close()
            stderr.close()

        gc.collect()
        return True, f"Agent v{AGENT_VERSION} deployed: {out_msg.strip()}"
    except Exception as e:
        close_ssh_connection(device.get("id", 0))
        return False, f"Failed to deploy agent: {str(e)}"

def _exec_ssh_step(client: paramiko.SSHClient, cmd: str):
    try:
        stdin, stdout, stderr = client.exec_command(cmd)
        stdout.channel.recv_exit_status()
        stdout.close()
        stderr.close()
    except Exception:
        pass

def uninstall_agent(device: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        client = _get_ssh_client(device, timeout=10)
        
        _exec_ssh_step(client, "sudo systemctl stop sc-monitoring-agent")
        _exec_ssh_step(client, "sudo systemctl disable sc-monitoring-agent")
        _exec_ssh_step(client, "sudo pkill -9 -f sc_agent.py; pkill -9 -f sc_agent.py")
        _exec_ssh_step(client, "sudo rm -f /etc/systemd/system/sc-monitoring-agent.service")
        _exec_ssh_step(client, "sudo rm -f /etc/systemd/system/multi-user.target.wants/sc-monitoring-agent.service")
        _exec_ssh_step(client, "sudo rm -f /etc/systemd/system/default.target.wants/sc-monitoring-agent.service")
        _exec_ssh_step(client, "sudo rm -rf /opt/sc-agent ~/.local/share/sc-agent /tmp/sc_agent.py /tmp/sc-monitoring-agent.service")
        _exec_ssh_step(client, "sudo systemctl daemon-reload")
        _exec_ssh_step(client, "sudo systemctl reset-failed")

        gc.collect()
        return True, "Agent stopped and uninstalled"
    except Exception as e:
        close_ssh_connection(device.get("id", 0))
        return False, str(e)
