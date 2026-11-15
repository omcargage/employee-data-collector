# EDC Standing Rules & Project Instructions

## Standing Rules
- **PRIVACY (non-negotiable):** Never record, log, store or transmit key values, typed text, window titles, screenshots, clipboard or URLs. Key events are reduced to a class (`char`, `backspace`, `delete`, `modifier`, `other`) plus timestamp inside the capture function, before anything else sees them.
- **Aggregated Metrics Only:** Only aggregated metrics leave the device. Raw events live only in memory until their window closes.
- **Missing Data Representation:** Missing data is never zero. Use null plus `coverage_ratio`. Gap types: `idle`, `away`, `unknown` (see `docs/metrics_spec.md` section 1).
- **Source of Truth:** `docs/metrics_spec.md` is the source of truth for every definition and threshold. Never invent a formula; if the spec is ambiguous, ask the user.
- **Pure Functions & Verified Tests:** Metric code is pure functions over plain data, with `pytest` tests with hand-computed expected values.
- **OS Abstraction Boundary:** OS-specific code lives only under `platforms/`, behind the `InputProvider` interface.
- **Shell Environment:** Instructions to the user must use Windows PowerShell commands.
- **Test Integrity:** Never claim a test passed without running it and showing real output.
