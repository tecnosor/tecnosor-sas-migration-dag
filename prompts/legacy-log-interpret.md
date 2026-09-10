# Interpret legacy SAS scheduler/export logs ({{node_id}})

You are interpreting legacy runtime logs that have NO guaranteed format.

## Context
```json
{{state}}
```

## Task
Read the raw log evidence referenced in state (or the material provided inside
the batch). Derive, for each recognizable batch job or process name:

- First and last observed execution.
- An estimate of typical cadence (daily / weekly / unknown).
- Errors or abnormal endings mentioned (as INFERRED findings only).
- Explicit gaps: lines you could not classify.

Rules:
1. Quote the exact log fragments you derived every conclusion from (source
   locators) and register them as `evidence` in the final envelope.
2. Mark anything you cannot confirm as `confidence: INFERRED` or `UNKNOWN`.
3. Never invent job names that do not appear in the text.
4. JSON envelope at the end (see agent-runtime constraints).
