# Security and data policy

LitHub Pavilion is a single-user, local research tool. It has no authentication and must not be exposed to the Internet or an untrusted LAN. The provided Compose file publishes only `127.0.0.1:8080` and keeps the API inside its private container network.

## Request boundaries

- API values are validated; SQL values use bound parameters/ORM expressions.
- Browser-origin state-changing requests from non-loopback sites are rejected. This is not a replacement for login if a public deployment is required.
- Outbound data-source clients use HTTPS, public-host validation and DNS-validated numeric IP connections with original TLS SNI. No automatic redirect following or environment proxy is enabled.
- Rendered external links reject credentials, control characters, unsafe schemes and local/private literal targets.
- No automatic PDF downloading is part of this release. Existing archive files are preserved, including during metadata deletion and link maintenance.

## Before sharing a repository

Never commit `.env`, API keys, mail credentials, local databases, backups, PDF archives, machine paths in generated logs, or node_modules. `.gitignore` and build-context excludes cover these artifacts, but inspect the staged file list before every first push.

Do not publish a screenshot that contains personal account information or credentials. Public source metadata is not necessarily licensed for arbitrary redistribution; this repository ships code and source configuration, not bulk paper contents.

## Reporting a concern

Report reproducible issues privately through the repository owner's available GitHub contact/security channel. Do not include real API keys or personal databases. Use a minimal fixture and remove credentials from request URLs and logs.

## Known boundaries

Upstream metadata is imperfect: venue association is not proof of main-track acceptance, historical metadata may contain mistakes, and topic keyword classification can overlap or be wrong. No full CCF catalog audit, network-wide vulnerability assessment, or complete paper link reachability certification is claimed.
