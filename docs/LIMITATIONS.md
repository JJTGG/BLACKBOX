# Known limitations

- The current API serves authenticated incident retrieval and action proposals; it is not a full administrative dashboard.
- Authentication is signed bearer-token authentication with explicit in-memory users, not a production identity provider or revocation service.
- The default Store now uses explicit SQLite transactions, busy handling, and hash-linked audit events. This is tested with independent-process fixtures but is not an externally immutable audit log.
- Task claims use durable retry budgets, per-claim fencing tokens, and continuous heartbeat renewal in orchestrator execution. These guarantees remain subject to the complete CI suite.
- Agents are deterministic fixture agents. No external LLM provider, live telemetry adapter, malware scanner, or infrastructure executor is included.
- Evidence excerpt presence is mechanically checked; semantic entailment remains unverified and unsupported claims stay explicit.
- The web application is a minimal authenticated incident view, not a complete operations console.
