"""One generic service which is configured entirely by the environment variables"""
import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram

from common.obs import (BUCKETS, SERVICE, call_service, install, log_event,
                        register_fault, set_deploy_handler, trace_id_var)

UPSTREAMS = json.loads(os.getenv("Upstreams", "{}"))
DB = os.getenv("Database enabled", "0") == "1"
DSN = os.getenv("DATABASE-URL", "")
RETRIES = int(os.getenv("should retry", "1"))
ACQUIRE_TIMEOUT = float(os.getenv("database timeout", "2.0"))
BASE = {"pool_max": int(os.getenv("database pool max", "8")),
        "query_ms": int(os.getenv("database query ms", "40")),
        "work_ms": int(os.getenv("database work ms", "8"))}

# S = mutable runtime state (changed by deploys / faults)
S = {"pool": None, "pool_max": BASE["pool_max"], "query_ms": BASE["query_ms"],
     "extra_ms": 0, "leak_task": None, "leaked": []}

DB_SIZE = Gauge("db_pool_size", "Open connections", ["service"])
DB_IN_USE = Gauge("db_pool_in_use", "Connections checked out", ["service"])
DB_MAX = Gauge("db_pool_max", "Pool max size", ["service"])
DB_WAITING = Gauge("db_pool_waiting", "Requests waiting for a connection", ["service"])
DB_WAIT = Histogram("db_pool_wait_seconds", "Time waiting for a connection", ["service"], buckets=BUCKETS)
DB_QUERY = Histogram("db_query_duration_seconds", "Query time", ["service"], buckets=BUCKETS)
DB_TIMEOUTS = Counter("db_pool_acquire_timeouts_total", "Acquire timeouts", ["service"])

client = httpx.AsyncClient(
    timeout=httpx.Timeout(float(os.getenv("CALL_TIMEOUT", "2.5"))),
    limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200))


async def make_pool(pool_max: int):
    return await asyncpg.create_pool(DSN, min_size=min(2, pool_max), max_size=pool_max)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DB:
        for _ in range(30):
            try:
                S["pool"] = await make_pool(S["pool_max"])
                break
            except Exception:
                await asyncio.sleep(1)
        DB_SIZE.labels(SERVICE).set_function(lambda: S["pool"].get_size() if S["pool"] else 0)
        DB_IN_USE.labels(SERVICE).set_function(
            lambda: (S["pool"].get_size() - S["pool"].get_idle_size()) if S["pool"] else 0)
        DB_MAX.labels(SERVICE).set_function(lambda: S["pool_max"])
        async with S["pool"].acquire() as c:
            await c.execute(f"""CREATE TABLE IF NOT EXISTS records_{SERVICE}(
                id SERIAL PRIMARY KEY, trace_id TEXT, created_at TIMESTAMPTZ DEFAULT now())""")
    log_event("started", db=DB, upstreams=list(UPSTREAMS))
    yield
    await stop_leak()
    if S["pool"]:
        await S["pool"].close()


app = FastAPI(lifespan=lifespan)
install(app)


#faults
async def start_leak(params: dict):
    if not DB:
        return
    n = int(params.get("leak", S["pool_max"] - 1))
    ramp = float(params.get("ramp_seconds", 0))
    pool = S["pool"]

    async def run():
        for _ in range(n):
            try:
                conn = await pool.acquire(timeout=30)
            except Exception:
                break
            S["leaked"].append((pool, conn))
            if ramp:
                await asyncio.sleep(ramp / n)

    S["leak_task"] = asyncio.create_task(run())


async def stop_leak():
    if S["leak_task"]:
        S["leak_task"].cancel()
        S["leak_task"] = None
    for pool, conn in S["leaked"]:
        try:
            await pool.release(conn)
        except Exception:
            pass
    S["leaked"].clear()


register_fault("pool_exhaustion", start_leak, stop_leak)


async def on_deploy(version: str):
    """v1.0 = healthy baseline. Anything else = the 'bad' build:
    extra CPU-ish latency everywhere; smaller pool + slower queries if DB-backed."""
    bad = version != "v1.0"
    S["extra_ms"] = 150 if bad else 0
    S["query_ms"] = BASE["query_ms"] * 4 if bad else BASE["query_ms"]
    new_max = max(2, round(BASE["pool_max"] * 0.4)) if bad else BASE["pool_max"]
    if DB and new_max != S["pool_max"]:
        old = S["pool"]
        S["pool"] = await make_pool(new_max)
        S["pool_max"] = new_max
        if old:
            asyncio.create_task(old.close())


set_deploy_handler(on_deploy)


# work
async def db_op():
    pool = S["pool"]  # capture so we release to the same pool even if a deploy swaps it
    t0 = time.perf_counter()
    DB_WAITING.labels(SERVICE).inc()
    try:
        conn = await pool.acquire(timeout=ACQUIRE_TIMEOUT)
    except asyncio.TimeoutError:
        DB_WAIT.labels(SERVICE).observe(time.perf_counter() - t0)
        DB_TIMEOUTS.labels(SERVICE).inc()
        log_event("db pool acquire timeout", level=40)
        raise HTTPException(503, "db pool timeout")
    finally:
        DB_WAITING.labels(SERVICE).dec()
    DB_WAIT.labels(SERVICE).observe(time.perf_counter() - t0)
    q0 = time.perf_counter()
    try:
        await conn.execute("SELECT pg_sleep($1)", S["query_ms"] / 1000)
        await conn.execute(f"INSERT INTO records_{SERVICE}(trace_id) VALUES($1)", trace_id_var.get())
    finally:
        DB_QUERY.labels(SERVICE).observe(time.perf_counter() - q0)
        await pool.release(conn)


async def call_downstream(target: str):
    last = "unknown"
    for attempt in range(RETRIES + 1):
        try:
            r = await call_service(client, target, "POST", f"{UPSTREAMS[target]}/work")
            if r.status_code < 500:
                return
            last = f"{target}_{r.status_code}"
        except httpx.HTTPError as e:
            last = f"{target}_{type(e).__name__}"
        log_event("downstream call failed", level=30, attempt=attempt + 1, reason=last)
    raise RuntimeError(last)


@app.post("/work")
async def work():
    own = (BASE["work_ms"] * random.uniform(0.5, 1.5) + S["extra_ms"]) / 1000
    await asyncio.sleep(own)
    if DB:
        await db_op()
    if UPSTREAMS:
        results = await asyncio.gather(*(call_downstream(t) for t in UPSTREAMS), return_exceptions=True)
        failed = [str(r) for r in results if isinstance(r, Exception)]
        if failed:
            raise HTTPException(502, f"downstream failed: {failed[0]}")
    return {"service": SERVICE, "ok": True}
