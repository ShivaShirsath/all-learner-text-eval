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

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _container_cpu_limit() -> int:
    """CPUs this container may actually use.

    os.cpu_count() reports the *host's* cores inside a container, so a pod
    limited to 2 vCPU on a 32-core node would start 32 workers that fight over
    2 CPUs. Read the cgroup quota instead (v2, then v1), falling back to the
    affinity mask / os.cpu_count() when no quota is set.
    """
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()
        if quota != "max":
            return max(1, int(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=5001,
        # WEB_CONCURRENCY overrides; default = container CPU limit.
        workers=_env_int("WEB_CONCURRENCY", _container_cpu_limit()),
        # Idle time a kept-alive connection stays open between requests (not
        # request duration). Must be longer than the caller's / gateway's idle
        # timeout, otherwise they reuse a socket we just closed -> 502.
        timeout_keep_alive=_env_int("KEEP_ALIVE_TIMEOUT", 65),
        # Per worker. Connections above this get an immediate 503.
        limit_concurrency=_env_int("LIMIT_CONCURRENCY", 1000),
    )