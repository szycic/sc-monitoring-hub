import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv()

db_env = os.getenv("DB_PATH", "./data/hub.db")
DB_PATH = Path(db_env) if Path(db_env).is_absolute() else (BASE_DIR / db_env).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

AGENT_SCRIPT_NAME = "sc_agent.py"
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "3.0"))

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
