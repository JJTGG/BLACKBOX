# Architecture

The integrated path is: authenticated HTTP request -> `application.py`/`http_api.py` -> domain persistence -> exact durable task claim -> specialist message persistence -> Commander reconciliation -> IndependentAuditor exact-output review -> persisted findings and reports.

Evidence is untrusted data. Supported findings carry a stored evidence ID, relation, note and excerpt. Unsupported findings carry `unsupported=true`; excerpt occurrence is mechanically checked, while semantic entailment remains an explicit uncertainty.

Messages are persisted with payload hashes and revisions. Task claims use a unique fence token, heartbeat, expiry recovery, retry limits and terminal failure. The HTTP boundary requires explicit configured users and a signing secret, validates expiring bearer tokens, enforces roles, serves `/`, and exposes only implemented incident/action routes.

This remains isolated SQLite software. Production identity, external LLMs, live telemetry, file quarantine, immutable external audit sinks and infrastructure executors are absent.
