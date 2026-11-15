# BLACKBOX

Autonomous Incident Response & Engineering Operations Platform.

## Current implementation

This branch contains an executable Python foundation with:

- SQLite-backed incident, evidence, task, finding, approval, and audit persistence.
- A constrained lifecycle state machine.
- Six independently implemented specialist agents with structured output contracts.
- Application-level orchestration with bounded retries and parallel specialist execution.
- Server-side role checks and explicit approval records for sensitive actions.
- Untrusted-evidence handling, prompt-injection detection, stale-result rejection, and a tamper-evident audit hash chain.
- Automated tests for security boundaries, concurrency, duplicate intake, lifecycle validation, and agent behavior.

This is not yet a production deployment or a claim of native autonomous-agent infrastructure. The orchestration layer is application code, and external execution adapters are intentionally absent.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

## Architecture

- `blackbox/core.py`: persistence, migrations, lifecycle, authorization, approvals, and audit chain.
- `blackbox/agents.py`: specialist specifications, bounded implementations, and output contracts.
- `blackbox/orchestrator.py`: task coordination, parallel execution, retries, and approval proposals.
- `tests/`: executable acceptance and security tests.
- `docs/`: architecture, threat model, and limitations.

## Evidence semantics

Evidence is preserved with provenance and is untrusted by default. Embedded instructions are never treated as platform instructions. Findings retain uncertainty and supporting/contradicting evidence; no external operation is executed by this repository.

## Verification status

The repository includes tests, but test execution must be performed by CI or a local Python environment. No test result is claimed until a workflow run is inspected.
