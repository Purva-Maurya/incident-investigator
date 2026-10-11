"""Single source of truth for the service graph. Used by the compose generator,
fault injector, experiment runner, and (later) the RCA engine's dependency graph."""
import os
import pathlib
from typing import Dict, List, Tuple

import yaml

ROOT = pathlib.Path(__file__).parent


def load(path=None) -> dict:
    path = pathlib.Path(path or os.getenv("TOPOLOGY", ROOT / "topology.yaml"))
    cfg = yaml.safe_load(path.read_text())
    names = set(cfg["services"])
    assert cfg["entry"] in names, "entry must be a service"
    for name, s in cfg["services"].items():
        s = cfg["services"][name] = s or {}
        for c in s.get("calls", []):
            assert c in names, f"{name} calls unknown service {c}"
    return cfg


def ports(cfg: dict) -> Dict[str, int]:
    """Host ports: entry service is 8000, others 8001.. in sorted order."""
    others = sorted(n for n in cfg["services"] if n != cfg["entry"])
    m = {cfg["entry"]: 8000}
    m.update({n: 8001 + i for i, n in enumerate(others)})
    return m


def edges(cfg: dict) -> List[Tuple[str, str]]:
    return [(n, c) for n, s in cfg["services"].items() for c in s.get("calls", [])]


def db_services(cfg: dict) -> List[str]:
    return [n for n, s in cfg["services"].items() if "db" in s]