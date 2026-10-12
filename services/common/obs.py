"""Shared observability + fault injection code for services.

Gives each service :
# Structured JSON logs (Service, trace_id, level, ts)
# RED metrics (Rate , error , duration) + inflight guage
# downstream service call metrics
# /metrics /health
# /admin/fault, admin/fault/clear, /admin/deploy
NOTE : Fault is not exposed in the metrics. which is our ground truth, so the investigator must infer it from outcomes only
"""
import asyncio
import json
import logging
import os
import random
import time
import sys
import uuid
from contextvars import ContextVar
from typing import Awaitable, Callable, Dict, Optional

import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

SERVICE = os.getenv("SERVICE_NAME", "unknown")
VERSION = {"current": os.getenv("SERVICE_VERSION", "v1.0")}
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

# logging
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "ts": time.time(),
            "level": record.levelname,
            "service": SERVICE,
            "trace_id": trace_id_var.get(),
            "msg": record.getMessage(),
        }
        d.update(getattr(record, "fields", {}))
        return json.dumps(d)


def _setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True  # we log requests ourselves
    logging.getLogger("httpx").setLevel(logging.WARNING)


_setup_logging()
_log = logging.getLogger(SERVICE)


def log_event(msg: str, level: int = logging.INFO, **fields) -> None:
    _log.log(level, msg, extra={"fields": fields})


# metrics now 
REQS = Counter("http_requests_total", "Requests handled", ["service", "route", "status"])
LAT = Histogram("http_request_duration_seconds", "Request latency", ["service", "route"], buckets=BUCKETS)
INFLIGHT = Gauge("http_inflight_requests", "In-flight requests", ["service"])
DOWN_LAT = Histogram("downstream_request_duration_seconds", "Outbound call latency", ["service", "target"], buckets=BUCKETS)
DOWN_REQS = Counter("downstream_requests_total", "Outbound calls", ["service", "target", "status"])
DEPLOY_TS = Gauge("service_last_deploy_timestamp_seconds", "Unix time of last deploy", ["service", "version"])

#faults
ACTIVE: Dict[str, dict] = {}
_HANDLERS: Dict[str, tuple] = {}

_DEPLOY_HANDLER: Dict[str, Optional[Callable[[str], Awaitable[None]]]] = {"fn": None}


def register_fault(name: str, start: Callable[[dict], Awaitable[None]], stop: Callable[[], Awaitable[None]]) -> None:
    _HANDLERS[name] = (start, stop)


def set_deploy_handler(fn: Callable[[str], Awaitable[None]]) -> None:
    _DEPLOY_HANDLER["fn"] = fn


class FaultRequest(BaseModel):
    type: str
    params: dict = {}


class DeployRequest(BaseModel):
    version: str


admin = APIRouter(prefix="/admin")


@admin.post("/fault")
async def set_fault(req: FaultRequest):
    ACTIVE[req.type] = req.params
    if req.type in _HANDLERS:
        await _HANDLERS[req.type][0](req.params)
    return {"active": ACTIVE}


@admin.post("/fault/clear")
async def clear_fault(req: FaultRequest):
    if req.type in ACTIVE:
        ACTIVE.pop(req.type)
        if req.type in _HANDLERS:
            await _HANDLERS[req.type][1]()
    return {"active": ACTIVE}


@admin.get("/faults")
async def list_faults():
    return {"active": ACTIVE, "version": VERSION["current"]}


@admin.post("/deploy")
async def deploy(req: DeployRequest):
    prev = VERSION["current"]
    VERSION["current"] = req.version
    DEPLOY_TS.labels(SERVICE, req.version).set(time.time())
    log_event("deploy", previous_version=prev, version=req.version)  # deploys are observable events
    if _DEPLOY_HANDLER["fn"]:
        await _DEPLOY_HANDLER["fn"](req.version)
    return {"version": req.version}


#  outbound calls
async def call_service(client: httpx.AsyncClient, target: str, method: str, url: str, **kw) -> httpx.Response:
    """Instrumented outbound HTTP call; propagates trace id."""
    headers = kw.pop("headers", {})
    headers["x-trace-id"] = trace_id_var.get()
    t0 = time.perf_counter()
    status = "error"
    try:
        r = await client.request(method, url, headers=headers, **kw)
        status = str(r.status_code)
        return r
    except httpx.TimeoutException:
        status = "timeout"
        raise
    finally:
        DOWN_LAT.labels(SERVICE, target).observe(time.perf_counter() - t0)
        DOWN_REQS.labels(SERVICE, target, status).inc()


#install
def install(app: FastAPI) -> None:
    app.include_router(admin)
    DEPLOY_TS.labels(SERVICE, VERSION["current"]).set(time.time())

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE, "version": VERSION["current"]}

    @app.middleware("http")
    async def obs_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/admin") or path in ("/metrics", "/health"):
            return await call_next(request)

        token = trace_id_var.set(request.headers.get("x-trace-id") or uuid.uuid4().hex[:16])
        INFLIGHT.labels(SERVICE).inc()
        t0 = time.perf_counter()
        status = 500
        try:
            lf = ACTIVE.get("latency_spike")
            if lf:
                await asyncio.sleep(lf.get("delay_ms", 500) / 1000 * random.uniform(0.8, 1.2))
            ef = ACTIVE.get("error_rate")
            if ef and random.random() < ef.get("rate", 0.3):
                status = 500
                return Response("injected error", status_code=500)
            resp = await call_next(request)
            status = resp.status_code
            return resp
        except Exception:
            _log.exception("unhandled")
            raise
        finally:
            dur = time.perf_counter() - t0
            route = request.scope.get("route")
            rpath = route.path if route else "unmatched"
            REQS.labels(SERVICE, rpath, str(status)).inc()
            LAT.labels(SERVICE, rpath).observe(dur)
            INFLIGHT.labels(SERVICE).dec()
            log_event("request", method=request.method, route=rpath, status=status,
                      duration_ms=round(dur * 1000, 1), version=VERSION["current"])
            trace_id_var.reset(token)