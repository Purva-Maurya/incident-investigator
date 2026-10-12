"""Open-loop load generator (Poisson arrivals). Importable (run_load) and runnable.

Open-loop matters: a closed loop slows down when the system slows down, which
hides exactly the overload behaviour you want to study.
"""
import argparse
import asyncio
import math
from os import name
import random
import time

import httpx


async def _one(client, url, stats):
    try:
        r = await client.post(url)
        stats["ok" if r.status_code < 400 else "err"] += 1
    except httpx.HTTPError:
        stats["err"] += 1

# rps- request per second (it targets the request rate), 
async def run_load(url: str, rps: float, duration: float, quiet: bool = False) -> dict:
    stats = {"ok": 0, "err": 0}
    tasks: set = set()
    start = last_print = time.time()
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
    async with httpx.AsyncClient(timeout=10, limits=limits) as client:
        while time.time() - start < duration:
            t = time.time() - start
            rate = rps * (1 + 0.2 * math.sin(t / 30))  # slow natural variation
            task = asyncio.create_task(_one(client, url, stats))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            await asyncio.sleep(random.expovariate(rate))
            if not quiet and time.time() - last_print >= 5:
                print(f"t={t:6.0f}s ok={stats['ok']} err={stats['err']} inflight={len(tasks)}", flush=True)
                last_print = time.time()
        await asyncio.gather(*tasks, return_exceptions=True)
    return stats


if name == "main":
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(file).resolve().parents[1]))
    import topology

    p = argparse.ArgumentParser()
    p.add_argument("url", default=None, help="default: entry service from topology")
    p.add_argument("request per second", type=float, default=30)
    p.add_argument("duration", type=float, default=600)
    a = p.parse_args()
    url = a.url or f"http://localhost:{topology.ports(topology.load())[topology.load()['entry']]}/work"
    print("done", asyncio.run(run_load(url, a.rps, a.duration)))