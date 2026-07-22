import gc
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sc_monitoring_hub import db
from sc_monitoring_hub import local_collector
from sc_monitoring_hub import ssh_manager
from sc_monitoring_hub import config
from sc_monitoring_hub.api import api_v1_router, ACTIVE_WEBSOCKETS

app = FastAPI(title="SC Monitoring Hub", version="1.0.0")

# Mount API v1 Router
app.include_router(api_v1_router)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

async def _poll_single_system(sys_node: Dict[str, Any]):
    try:
        if sys_node["is_local"]:
            metrics = local_collector.get_local_metrics()
        else:
            metrics = await asyncio.to_thread(ssh_manager.fetch_ssh_metrics, sys_node)
        
        db.save_metrics(sys_node["id"], metrics)
        db.update_system_status(sys_node["id"], "online")

        # Stream metrics to connected WebSockets
        sys_id = sys_node["id"]
        if sys_id in ACTIVE_WEBSOCKETS and ACTIVE_WEBSOCKETS[sys_id]:
            for ws in list(ACTIVE_WEBSOCKETS[sys_id]):
                try:
                    await ws.send_json(metrics)
                except Exception:
                    pass
    except Exception as e:
        db.update_system_status(sys_node["id"], "offline", str(e))

async def background_metric_poller():
    poll_count = 0
    while True:
        try:
            systems = db.list_systems()
            if systems:
                await asyncio.gather(*[_poll_single_system(s) for s in systems])
        except Exception as e:
            print(f"[Poller Error] {e}")
            
        poll_count += 1
        # Run garbage collection every 20 polling cycles (~1 minute) to keep RAM low
        if poll_count % 20 == 0:
            gc.collect()

        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

@app.on_event("startup")
async def startup_event():
    db.init_db()
    asyncio.create_task(background_metric_poller())

# HTML Page Routes
@app.get("/")
@app.get("/dashboard")
@app.get("/dashboard/{system_id}")
@app.get("/systems/{system_id}/dashboard")
@app.get("/systems")
@app.get("/htop")
@app.get("/htop/{system_id}")
@app.get("/systems/{system_id}/htop")
@app.get("/journal")
@app.get("/journal/{system_id}")
@app.get("/systems/{system_id}/journal")
async def page_view(request: Request, system_id: Optional[int] = None):
    return templates.TemplateResponse(request=request, name="index.html", context={"systems": db.list_systems()})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("sc_monitoring_hub.main:app", host=config.HOST, port=config.PORT, reload=True)
