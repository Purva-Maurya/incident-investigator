# AI Production Incident Investigator

An AI-assisted system for investigating production incidents in microservice architectures. The project is being built to detect abnormal service behavior, correlate supporting evidence, rank potential root causes, and generate evidence-grounded incident reports.

> **Project status:** Early development. The data contracts, service-topology configuration, and initial Docker service setup are in progress. Features listed as planned are not yet implemented.

## Why this project?

When a production system becomes slow or starts returning errors, engineers often need to inspect metrics, logs, traces, deployments, and service dependencies to work out what happened. This project aims to bring those signals together into a structured investigation that helps explain **what happened, where it may have started, and which evidence supports the conclusion**.

## Planned workflow

1. **Run a microservice environment** with a gateway, checkout, and payment service.
2. **Collect telemetry** such as latency, error rates, and database connection-pool utilization.
3. **Detect anomalies** by comparing observed metrics with a baseline.
4. **Collect and correlate evidence** from anomalies, service dependencies, deployment events, and other signals.
5. **Rank root-cause candidates** using a transparent scoring approach.
6. **Generate an incident report** with claims linked to evidence IDs.
7. **Evaluate the investigation** against fault-injection ground truth that is kept separate from the investigator's inputs.

The goal is to support investigation and explanation, not merely alert that a metric crossed a threshold.

## Architecture

```text
                    ┌─────────────────────┐
                    │       Gateway       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │      Checkout       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │       Payment       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │      PostgreSQL     │
                    └─────────────────────┘

Telemetry → Anomaly Detection → Evidence & RCA → Incident Report
```

The service graph is configured in `topology.yaml`. The current topology describes the gateway calling checkout, checkout calling payment, and payment using a database.

## Current project structure

```text
incident-investigator/
├── schemas/
│   ├── __init__.py
│   └── models.py              # Shared Pydantic data contracts
├── services/
│   ├── common/
│   │   └── __init__.py        # Shared service utilities (planned)
│   ├── app/                   # Microservice application code (in progress)
│   ├── Dockerfile             # Shared service image
│   └── requirements.txt       # Service dependencies
├── scripts/                   # Experiment and utility scripts (planned)
├── loadgen/                   # Load-generation code (planned)
├── topology.yaml              # Service graph and database settings
├── topology.py                # Topology loading and helper functions
├── requirements-dev.txt       # Local development dependencies
└── README.md
```

## Technology stack

- **Python 3.11+** — core implementation
- **FastAPI** — HTTP services
- **Docker / Docker Compose** — local microservice environment
- **Pydantic** — structured models and validation
- **PyYAML** — topology configuration
- **HTTPX** — service-to-service HTTP requests and testing
- **Prometheus client** — planned metrics instrumentation
- **PostgreSQL / asyncpg** — planned database integration
- **NumPy / pandas** — planned metric processing and analysis
- **pytest** — testing

## Data contracts

`schemas/models.py` defines the shared structures used across pipeline stages:

- `FaultRecord` — ground truth for controlled fault-injection experiments; must remain hidden from the investigator during evaluation.
- `Anomaly` — an unusual metric observation, including onset, severity, baseline, and peak value.
- `Evidence` — a traceable clue with an ID, type, description, timestamp, and strength.
- `Candidate` — a possible root cause with a score and supporting evidence IDs.
- `Investigation` — the structured findings passed to the report-generation stage.
- `Claim` — a report statement linked to evidence IDs.
- `IncidentReport` — the final structured incident summary.

These models define data shapes and validation rules; they do not implement anomaly detection or root-cause analysis by themselves.

## Getting started

### Prerequisites

Install:

- Python 3.11 or newer
- Git
- Docker Desktop with Docker Compose
- Visual Studio Code (optional)

### 1. Clone the repository

```bash
git clone https://github.com/<YOUR_USERNAME>/incident-investigator.git
cd incident-investigator
```

Replace `<YOUR_USERNAME>` with the GitHub account that owns the repository.

### 2. Create and activate a virtual environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install development dependencies

```bash
python -m pip install -r requirements-dev.txt
```

### 4. Check the data models

```bash
python -c "import schemas.models; print('schemas ok')"
```

### 5. Check the service topology

```bash
python -c "import topology; c=topology.load(); print(topology.ports(c))"
```

With the current topology, the expected port mapping is:

```text
{'gateway': 8000, 'checkout': 8001, 'payment': 8002}
```

These checks validate the models and topology helpers; they do **not** mean the microservices or full investigation pipeline are running yet.

## Development roadmap

- [x] Define shared Pydantic data contracts.
- [x] Add YAML-based service topology configuration and helper functions.
- [ ] Implement the gateway, checkout, and payment services.
- [ ] Add Docker Compose orchestration and health checks.
- [ ] Add Prometheus metrics and a load generator.
- [ ] Implement controlled fault injection and keep ground truth separate.
- [ ] Build anomaly detection and evidence extraction.
- [ ] Rank root-cause candidates with an interpretable score breakdown.
- [ ] Generate evidence-grounded incident reports.
- [ ] Evaluate root-cause accuracy, detection delay, and report grounding across repeated experiments.

## Evaluation principles

The project is intended to be evaluated with repeatable experiments and measurable outcomes, including:

- Whether an injected fault is detected.
- Whether the suspected root-cause service and fault type match the hidden ground truth.
- How quickly the system detects symptoms and identifies a plausible cause.
- Whether report claims reference valid, relevant evidence.
- How performance changes across different fault types and repeated runs.

Metrics and results will be documented after the corresponding components and experiments are implemented. No performance claims are made at this stage.

## Security and data handling

- Do not commit `.env` files, credentials, API keys, or other secrets.
- Keep generated datasets and local-only artifacts out of Git unless they are intentionally prepared for sharing.
- Keep `faults/ground_truth.jsonl` out of the investigator's input path and exclude it from version control when it contains experiment ground truth.
- Use synthetic or appropriately anonymized telemetry for public demonstrations.

## Contributing

This is an evolving engineering project. Issues, suggestions, and constructive feedback are welcome. Please describe reproducible bugs and include relevant environment details when reporting them.

## License

No license has been added yet. Until a license is selected and included in the repository, reuse and redistribution permissions are not explicitly granted.
