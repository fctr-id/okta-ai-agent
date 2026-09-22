# Reusable queries

Enable the experimental library with `QUERY_PROCEDURES_ENABLED=true`.
Successful retrieval scripts can be reused against current data or adapted when
their saved evidence supports the requested change. Result rows are not cached
for other users. Generic procedures are shared within the tenant; other eligible
procedures remain private to their owner.

## Saving a query

Result synthesis still extracts purpose, entities, scope, parameters, and sharing
classification. After successful execution and code validation, Tako queues the
candidate in the SQLite `query_procedure_admissions` table. Pending candidates
are not available for reuse.

A background check uses the configured reasoning model to compare the new query
with related, accessible entries from `query_procedures`. It receives questions,
purpose, scope, entities, parameter names, classification, data source, and output
field names. It receives no scripts, SQL/API evidence, result summaries, or data
rows. Private query text can contain identifiers, just as in normal processing;
another user's private queries are excluded.

The decision is:

- **Duplicate:** keep the existing entry and record another successful execution.
  Do not replace its script or change its ownership.
- **Useful variant:** save separately when scope, date window, population,
  relationships, or requested output differs.
- **Distinct:** save a new retrieval need, including cases where equivalence is
  uncertain.

Entity overlap selects up to 32 comparison entries within
`QUERY_PROCEDURES_CATALOG_CHARS`. This is a semantic comparison of retrieval
requirements, not proof that two scripts are equivalent or that an answer is
correct. Existing library duplicates are not retroactively merged.

## Background processing and recovery

The server checks for pending work at startup and every five seconds. The model
call does not delay web, Slack, or Teams responses. A query may not be available
for reuse immediately after its answer appears; look for `Procedure admission`
in the server log to see the decision.

Failed checks remain pending, retrying after five minutes with backoff up to one
hour. A check has a 60-second model timeout. Tenant-level leases prevent multiple
workers from admitting overlapping candidates concurrently; interrupted leases
can be recovered after two minutes. Graceful shutdown releases the lease early.
Persist the application's database volume to retain pending work across container
replacement. The table is created automatically during database initialization.

`QUERY_PROCEDURES_MAX_PER_TENANT` (default 100) caps the admitted library and,
separately, the pending queue. A full queue preserves pending work and logs that
the new candidate was not queued; the user's result still succeeds. Admitted
entries retain the existing popularity/recency policy.

The CLI displays and exports results first, then spends up to 65 seconds trying
to finish admission before exiting. If unfinished, the candidate remains pending
for the server or a later CLI admission attempt. Evaluation reports include
admission status; admission model usage is logged separately from query usage.
