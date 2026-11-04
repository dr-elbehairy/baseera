# Glossary (generated from `baseera/core/catalog.py`)

Run `python -m baseera.cli glossary` or `GET /api/admin/glossary` for the live version. Every code the platform shows has an
Arabic label defined in one place (`core/catalog.py`): asset-code prefixes, kinds, street/criticality, failure-mode classes
A/B/C, priority tiers, actions, statuses, sources, report and work-order kinds, telemetry channels, metrics, and the parts
and checklist per failure mode. English codes are kept in the database and in uploaded files so they stay interoperable
with the municipality's systems; the UI renders the Arabic label next to the code.
