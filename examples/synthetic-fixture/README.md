# SYNTHETIC FIXTURE (foundation demo only)

All material in this tree is **synthetic** and deliberately minimal. It exists to
exercise the SASsessment foundation graph (registration, discovery, request
pause/resume, quality gate, checkpoint, audit export).

Contents:
- `sources/proceso_1.sas` — reads `cust.customer_master`, writes `cust.customer_dq`, includes `shared_macros/fmt_check.sas`
- `sources/proceso_2.sas` — reads `cust.customer_dq` only
- `sources/shared_macros/fmt_check.sas` — shared include/macro
- `runtime/scheduler_export.log` — execution log for `proceso_1` ONLY (proceso_2 intentionally has no runtime evidence)
- `dictionary/data_dictionary.csv` — maps tables to owning applications

The Oracle `all_dependencies` export is intentionally ABSENT: the demo must
generate a DBA request, pause the lineage branch, then resume it after a
simulated DBA result batch is added.
