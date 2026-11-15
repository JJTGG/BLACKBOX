# Threat model

## Assets

Incident records, uploaded evidence, agent findings, approvals, audit history, credentials, and report integrity.

## Trust boundaries

Client to server; uploaded evidence to the analysis domain; agent outputs to the persistence layer; application to SQLite; approver to proposed sensitive actions.

## Threats and mitigations

| Threat | Mitigation | Residual risk |
|---|---|---|
| Prompt injection in evidence | Evidence is marked untrusted; security agent detects injection; no evidence instruction is executed | Detection patterns are heuristic and require model-independent review |
| Unauthorized case mutation | Domain-level role authorization, not UI hiding | HTTP adapter and identity provider are not included yet |
| Unauthorized approval | Only approver/administrator roles can decide approval records | No production identity provider integration |
| Audit tampering | Hash-linked audit chain and verification method | Database administrators can still alter both data and code; deploy immutable storage in production |
| Stale overwrite | Incident revisions reject older finding revisions | Distributed worker leases are future work |
| SQL injection | Parameterized SQLite queries | Future adapters must preserve parameterization |
| Secret leakage | `.gitignore`, placeholder env file, no credentials in fixtures | CI secret scanning is future work |
| Malicious files | Foundation stores textual evidence only; no file execution | Upload MIME, size, malware scanning, and quarantine are future work |

## Security assumptions

This repository is isolated test software. It does not connect to production infrastructure, send communications, deploy code, modify databases outside its own SQLite file, or execute commands from evidence.
