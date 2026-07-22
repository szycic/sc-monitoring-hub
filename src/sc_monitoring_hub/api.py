import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from sc_monitoring_hub import db
from sc_monitoring_hub import local_collector
from sc_monitoring_hub import ssh_manager
from sc_monitoring_hub import agent_template

api_v1_router = APIRouter(prefix="/api/v1")

# Active WebSocket connections grouped by system_id
ACTIVE_WEBSOCKETS: Dict[int, List[WebSocket]] = {}

# Pydantic Schemas
class SystemCreateSchema(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str = "root"
    auth_type: str = "password"
    auth_credential: Optional[str] = ""
    mode: str = "agentless"
    agent_port: int = 9990

class SshTestSchema(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    auth_type: str = "password"
    auth_credential: Optional[str] = ""

class ProcessKillSchema(BaseModel):
    pid: int
    signal: int = 9

@api_v1_router.get("/systems")
async def api_list_systems():
    systems = db.list_systems()
    result = []
    for sys_node in systems:
        sys_dict = dict(sys_node)
        if sys_dict.get("mode") == "agent":
            latest = db.get_latest_metrics(sys_dict["id"])
            if latest and "agent_version" in latest:
                sys_dict["agent_version"] = latest["agent_version"]
            else:
                sys_dict["agent_version"] = agent_template.AGENT_VERSION
        result.append(sys_dict)
    return result

@api_v1_router.post("/systems")
async def api_add_system(payload: SystemCreateSchema):
    sys_id = db.add_system(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        auth_type=payload.auth_type,
        auth_credential=payload.auth_credential or "",
        mode=payload.mode,
        agent_port=payload.agent_port
    )
    sys_node = db.get_system(sys_id)
    if payload.mode == "agent" and sys_node:
        asyncio.create_task(asyncio.to_thread(ssh_manager.deploy_agent, sys_node))
    return sys_node

@api_v1_router.delete("/systems/{system_id}")
async def api_delete_system(system_id: int):
    sys_node = db.get_system(system_id)
    if not sys_node:
        raise HTTPException(status_code=404, detail="System not found")
    if sys_node["is_local"]:
        raise HTTPException(status_code=400, detail="Cannot delete local hub server")
    ssh_manager.close_ssh_connection(system_id)
    db.delete_system(system_id)
    return {"status": "deleted", "id": system_id}

@api_v1_router.post("/systems/test-ssh")
async def api_test_ssh(payload: SshTestSchema):
    success, msg = await asyncio.to_thread(
        ssh_manager.test_ssh_connection,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        auth_type=payload.auth_type,
        auth_credential=payload.auth_credential or ""
    )
    if not success:
        return {"success": False, "error": msg}
    return {"success": True, "message": msg}

@api_v1_router.get("/systems/{system_id}/metrics")
async def api_get_metrics(system_id: int):
    sys_node = db.get_system(system_id)
    if not sys_node:
        raise HTTPException(status_code=404, detail="System not found")

    if sys_node["is_local"]:
        return local_collector.get_local_metrics()
    
    metrics = db.get_latest_metrics(system_id)
    if not metrics:
        metrics = await asyncio.to_thread(ssh_manager.fetch_ssh_metrics, sys_node)
    return metrics

@api_v1_router.get("/systems/{system_id}/history")
async def api_get_history(system_id: int, limit: int = 30):
    return db.get_metrics_history(system_id, limit=limit)

@api_v1_router.get("/systems/{system_id}/htop")
async def api_get_htop(system_id: int, search: str = "", limit: int = 100, sort_by: str = "cpu_percent"):
    sys_node = db.get_system(system_id)
    if not sys_node:
        raise HTTPException(status_code=404, detail="System not found")
    
    if sys_node["is_local"]:
        return local_collector.get_local_processes(search=search, limit=limit, sort_by=sort_by)
    return await asyncio.to_thread(ssh_manager.fetch_ssh_processes, sys_node, search=search, limit=limit, sort_by=sort_by)

@api_v1_router.post("/systems/{system_id}/process/kill")
async def api_kill_process(system_id: int, payload: ProcessKillSchema):
    sys_node = db.get_system(system_id)
    if not sys_node:
        raise HTTPException(status_code=404, detail="System not found")
    
    if sys_node["is_local"]:
        res = local_collector.kill_local_process(payload.pid, payload.signal)
    else:
        res = await asyncio.to_thread(ssh_manager.kill_ssh_process, sys_node, payload.pid, payload.signal)
    return {"success": res, "pid": payload.pid}

@api_v1_router.get("/systems/{system_id}/journalctl")
async def api_get_journalctl(system_id: int, search: str = "", unit: str = "", priority: str = "", lines: int = 100):
    sys_node = db.get_system(system_id)
    if not sys_node:
        raise HTTPException(status_code=404, detail="System not found")
    
    if sys_node["is_local"]:
        return local_collector.get_local_journal(unit=unit, priority=priority, lines=lines, search=search)
    return await asyncio.to_thread(ssh_manager.fetch_ssh_journal, sys_node, unit=unit, priority=priority, lines=lines, search=search)

@api_v1_router.post("/systems/{system_id}/deploy-agent")
async def api_deploy_agent(system_id: int):
    sys_node = db.get_system(system_id)
    if not sys_node or sys_node["is_local"]:
        raise HTTPException(status_code=400, detail="Invalid target system")
    
    success, msg = await asyncio.to_thread(ssh_manager.deploy_agent, sys_node)
    if success:
        db.update_system_mode(system_id, "agent")
        return {"success": True, "message": msg}
    return {"success": False, "error": msg}

@api_v1_router.post("/systems/{system_id}/uninstall-agent")
async def api_uninstall_agent(system_id: int):
    sys_node = db.get_system(system_id)
    if not sys_node or sys_node["is_local"]:
        raise HTTPException(status_code=400, detail="Invalid target system")
    
    success, msg = await asyncio.to_thread(ssh_manager.uninstall_agent, sys_node)
    if success:
        db.update_system_mode(system_id, "agentless")
        return {"success": True, "message": msg}
    return {"success": False, "error": msg}

@api_v1_router.websocket("/systems/{system_id}/live")
async def websocket_system_live(websocket: WebSocket, system_id: int):
    await websocket.accept()
    if system_id not in ACTIVE_WEBSOCKETS:
        ACTIVE_WEBSOCKETS[system_id] = []
    ACTIVE_WEBSOCKETS[system_id].append(websocket)
    
    try:
        sys_node = db.get_system(system_id)
        if sys_node:
            initial_metrics = local_collector.get_local_metrics() if sys_node["is_local"] else db.get_latest_metrics(system_id)
            if initial_metrics:
                await websocket.send_json(initial_metrics)
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if system_id in ACTIVE_WEBSOCKETS and websocket in ACTIVE_WEBSOCKETS[system_id]:
            ACTIVE_WEBSOCKETS[system_id].remove(websocket)
