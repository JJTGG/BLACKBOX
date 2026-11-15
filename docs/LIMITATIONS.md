# Known limitations

This foundation is deliberately honest about incomplete delivery:

- No web interface, HTTP authentication/session layer, or user-management UI yet.
- No report exporter or BBX-001/BBX-002 seed command yet.
- No external LLM provider or live observability/security integrations; agent logic is deterministic fixture logic.
- Task table exists, but a lease-based crash-recovery worker is not implemented yet.
- Evidence ingestion accepts text and metadata; production upload quarantine and malware scanning are not implemented.
- Audit chaining is tamper-evident, not an immutable external append-only log.
- Tests are committed but have not been executed in this environment; CI verification is still required.
