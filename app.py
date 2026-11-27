import os
import time
import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from routes import router
from metrics import setup_metrics


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)

app = FastAPI(
    docs_url='/api/docs',
    openapi_url='/api/openapi.json'
)

START_TIME = time.time()

app.include_router(router)
setup_metrics(app)

# Health check endpoint
@app.get("/ping")
async def health_check():
    return {
        "status": True,
        "message": "Text Eval Service is working"
    }

# Deep health check endpoint
@app.get("/health")
async def deep_health():
    return {
        "status": "ok",
        "uptime": time.time() - START_TIME,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

def _worker_count() -> int:
    """WEB_CONCURRENCY if set, else the container's CPU limit, else os.cpu_count().

    Inside a container os.cpu_count() returns the node's cores, so a pod limited
    to 2 CPUs on a 16-core node started 16 workers fighting over 2 CPUs.
    """
    try:
        return max(1, int(os.environ["WEB_CONCURRENCY"]))
    except (KeyError, ValueError):
        pass
    try:  # cgroup v2: "<quota> <period>" or "max <period>"
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()
        if quota != "max":
            return max(1, int(quota) // int(period))
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    return os.cpu_count() or 1


if __name__ == "__main__":
    import uvicorn
    num_workers = _worker_count()

    uvicorn.run(
        "app:app", 
        host="0.0.0.0", 
        port=5001, 
        workers=num_workers,
        timeout_keep_alive=300,  # 5 min for large audio file
        limit_concurrency=1000
    )