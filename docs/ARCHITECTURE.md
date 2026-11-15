# Architecture

BLACKBOX is a layered application:

1. **Persistence** — SQLite with foreign keys, indexes, transactions, migrations, and revisions.
2. **Domain** — lifecycle transitions, role authorization, approval state, provenance, findings, and audit-chain verification.
3. **Agents** — six separate bounded implementations with explicit task allowlists and structured contracts.
4. **Orchestration** — application-level coordination; parallel specialist calls use a bounded pool, retry cap, revision checks, and preserved audit records.
5. **Presentation boundary** — not included in this foundation; HTTP/UI adapters must call domain methods rather than bypass authorization.

## Lifecycle

`intake -> validation -> investigation -> correlation -> risk_assessment -> human_review -> reporting -> resolution`.

Suspension and cancellation are explicit transitions. Invalid transitions raise `InvalidTransition` and create rejected audit events. Sensitive actions are proposals until an approver authorizes them; this repository performs no infrastructure-side effects.

## Message contract

Every completed invocation returns `AgentMessage` with message ID, incident ID, agent, task, input fingerprint, structured output, status, timestamp, and revision. Output requires `findings`; each finding includes kind, statement, supporting evidence, contradicting evidence, and confidence.

## Concurrency and recovery direction

SQLite locking and revision checks protect this foundation. Durable task rows exist in the schema; a production worker should claim them with leases and resume incomplete tasks after restart. Exactly-once external execution is not claimed.
