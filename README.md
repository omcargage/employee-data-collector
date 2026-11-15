# Employee Data Collector (EDC)

A privacy-first, cross-platform desktop agent collecting aggregated behavioural metrics from laptops.

## Architecture Overview
- **Agent (`agent/edc_agent/`)**: Desktop collector running locally on the employee machine.
  - `collectors/` & `platforms/`: In-memory input listeners isolated behind OS-specific `InputProvider` interfaces.
  - `privacy/`: Immediate redaction boundary reducing keystrokes to coarse event classes and timestamps.
  - `metrics/`: Pure numerical functions calculating 15-minute and daily rollups defined in `docs/metrics_spec.md`.
  - `storage/`: Embedded SQLite storage staging local aggregated rollups and delivery batches.
  - `transport/`: HTTPS client uploading verified rollups to the backend with retry policies.
- **Backend (`backend/`)**: FastAPI service receiving, validating, and persisting aggregated metric batches.
- **Shared (`shared/`)**: Pydantic schemas defining the strict data contract between agent and backend.
- **Docs (`docs/`)**: Metrics specification and schemas defining formulas, thresholds, and null handling.
- **Scripts (`scripts/`)**: Development, deployment, and data verification scripts.
