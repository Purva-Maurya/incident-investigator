"""Generate docker-compose.yml and infra/prometheus.yml from a topology file.

  python scripts/gen_compose.py                          # topology.yaml
  python scripts/gen_compose.py topology.large.yaml
"""
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import topology  # noqa: E402

cfg = topology.load(sys.argv[1] if len(sys.argv) > 1 else None)
ports = topology.ports(cfg)
dbs = topology.db_services(cfg)

compose = {"services": {}}
if dbs:
    compose["services"]["postgres"] = {
        "image": "postgres:16",
        "environment": {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"},
        "command": ["postgres", "-c", "max_connections=300"],
        "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U app -d app"], "interval": "3s", "retries": 20},
    }

for name, s in cfg["services"].items():
    env = {"SERVICE_NAME": name,
           "UPSTREAMS": json.dumps({c: f"http://{c}:8000" for c in s.get("calls", [])})}
    depends = {c: {"condition": "service_started"} for c in s.get("calls", [])}
    if "db" in s:
        env.update({"DB_ENABLED": "1", "DATABASE_URL": "postgresql://app:app@postgres:5432/app",
                    "DB_POOL_MAX": str(s["db"].get("pool_max", 8)),
                    "DB_QUERY_MS": str(s["db"].get("query_ms", 40))})
        depends["postgres"] = {"condition": "service_healthy"}
    compose["services"][name] = {
        "image": "incident-app",
        "build": {"context": "./services", "dockerfile": "Dockerfile"},
        "environment": env,
        "ports": [f"{ports[name]}:8000"],
        **({"depends_on": depends} if depends else {}),
    }

compose["services"]["prometheus"] = {
    "image": "prom/prometheus",
    "volumes": ["./infra/prometheus.yml:/etc/prometheus/prometheus.yml:ro"],
    "ports": ["9090:9090"],
}

prom = {"global": {"scrape_interval": "5s"},
        "scrape_configs": [{"job_name": n, "static_configs": [{"targets": [f"{n}:8000"]}]}
                           for n in cfg["services"]]}

(ROOT / "docker-compose.yml").write_text(yaml.safe_dump(compose, sort_keys=False))
(ROOT / "infra").mkdir(exist_ok=True)
(ROOT / "infra" / "prometheus.yml").write_text(yaml.safe_dump(prom, sort_keys=False))
print(f"wrote docker-compose.yml + infra/prometheus.yml for {len(cfg['services'])} services")
print("host ports:", ports)