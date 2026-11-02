# Security & compliance baseline (v0.1)

| area | control | where |
|---|---|---|
| Data residency | deploy only in a cloud region inside KSA; no external analytics; weather from a local/open feed with no operational data sent out | docker-compose / deployment |
| Personal data (PDPL) | reporter identity never stored — salted SHA-256 at ingestion; no name/phone columns anywhere | `services/ingest/base.py::reporter_hash` |
| Identity | JWT (HS256) 15-min access + 7-day refresh; passwords PBKDF2-SHA256; demo users disabled in production; OIDC/SSO ready | `core/security.py` |
| Authorisation | RBAC: supervisor / technician / manager / admin; least privilege per router | `core/security.py::require` |
| Audit | approvals, overrides, outcomes, ingest runs, model training, quarantine resolution → append-only `sec_audit_log` | `core/security.py::audit` |
| Transport & storage | TLS 1.2+ at the edge (WAF); encrypted volumes; secrets via environment from a secret manager, never in git | `.env.example`, `.gitignore` |
| Attack surface | read-only exports from municipal systems; no writes to CMMS/Balady; rate limiting at the edge; API behind `/api` | architecture |
| Human in the loop | the weekly list is *proposed* until a supervisor approves; the system never issues work orders | `routers/lists.py` |
| Idempotency | `external_ref` / `client_ref` unique keys prevent duplicate rows on replay | models, pipelines, field router |
| Reference frameworks | NCA ECC essential controls; PDPL; checklist reviewed before the shadow pilot | this file |

Before pilot: rotate `BASEERA_JWT_SECRET`, set `BASEERA_ENV=production`, configure OIDC, enable DB backups (35-day retention),
run OWASP ZAP baseline against staging, and record the review in `docs/adr/`.
