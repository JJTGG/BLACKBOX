# BLACKBOX

Python 3.11+ incident-response foundation for isolated test data. It is not a production deployment.

## Start

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
export BLACKBOX_SESSION_SECRET='replace-with-a-random-secret'
python -c "from blackbox.core import Store,Role; from blackbox.http_api import Authenticator; from blackbox.application import serve_application; import hashlib,os; users={'observer':(hashlib.sha256(b'change-me').hexdigest(),Role.OBSERVER)}; serve_application(Store('blackbox.sqlite3'),Authenticator(users,secret=os.environ['BLACKBOX_SESSION_SECRET'])).serve_forever()"
```

The application serves `/` and authenticated `GET /incidents/{incident_id}`. Sensitive proposals use `POST /incidents/{incident_id}/actions` and require an investigator, commander, or administrator. No infrastructure operation is executed.

## Implementation

- `blackbox/core.py`: SQLite persistence, lifecycle, authorization, approvals, and audit chain.
- `blackbox/agents.py`: six bounded agents; each finding explicitly has evidence references or `unsupported=true`.
- `blackbox/validation.py`: record-aware evidence checks, structured claim relationships, commander reconciliation, and exact-output audit.
- `blackbox/message_store.py`: durable messages, hashes, and revision history.
- `blackbox/task_worker.py`: exact claims, leases, fencing tokens, heartbeat, retry exhaustion, and recovery.
- `blackbox/orchestrator.py`: durable execution, message persistence, reconciliation, and audit path.
- `blackbox/application.py`: HTTP entry point serving the web page and API.

## Verification

Run `pytest -v` locally. `.github/workflows/ci.yml` runs syntax compilation and the full suite on Python 3.11–3.14. Committed tests are not execution evidence; inspect workflow conclusions.

## Limitations

No production identity provider, external LLM, live telemetry integration, file quarantine, immutable external audit sink, or infrastructure executor is included. Multi-process SQLite audit guarantees remain subject to the concurrency tests and are not a production claim.
