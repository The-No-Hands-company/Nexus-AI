# External Process-Bound Progress Gates

This file defines measurable, evidence-based gates for external process-bound items so feature hardening can proceed in parallel.

## Gate Scale

- `G0` Not started
- `G1` Scope and owner defined
- `G2` Evidence framework and templates ready
- `G3` External engagement started
- `G4` External validation in progress
- `G5` Completed/approved

## Current Gate Register

| Item | Current Gate | Next Gate Target | Evidence File |
|---|---|---|---|
| SOC 2 Type II | G3 | G4 | `docs/production-readiness/soc2_type2_readiness.md` |
| ISO 27001 ISMS | G3 | G4 | `docs/production-readiness/iso27001_isms_readiness.md` |
| HIPAA BAA | G3 | G4 | `docs/production-readiness/hipaa_baa_readiness.md` |
| Pentest + CVE SLA | G3 | G4 | `docs/production-readiness/pentest_and_cve_sla_program.md` |
| FedRAMP path | G3 | G4 | `docs/production-readiness/fedramp_path_readiness.md` |
| PCI DSS trigger governance | G3 | G4 (if billing scope changes) | `docs/production-readiness/pci_dss_scope_and_trigger.md` |
| Published uptime SLA | G3 | G4 | `docs/production-readiness/uptime_sla_draft.md` |

## Parallel Hardening Rule

Any item at `G2` or above is considered ready for internal hardening tracks on already-implemented features, provided no hard blocker exists in runtime safety or compliance boundaries.
