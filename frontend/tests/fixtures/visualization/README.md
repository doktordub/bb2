# Frontend Visualization Fixtures

The canonical shared visualization happy-path fixtures remain under `backend/tests/fixtures/visualization/` and are loaded directly by frontend contract tests.

This directory contains frontend-local edge fixtures that are useful before later phases freeze additional backend public contracts:

- `unsupported_chart_artifact_v1.json`
- `reference_mode_artifact_provisional_v1.json`
- `expired_reference_error_provisional_v1.json`
- `multi_artifact_chat_response_provisional_v1.json`

These edge fixtures are intentionally marked `contract_status: provisional` because backend phase 0 deferred the public reference-mode artifact route and the multi-artifact runtime contract is not yet implemented.