# Reusable queries

Enable the experimental library with `QUERY_PROCEDURES_ENABLED=true`.
Successful retrieval scripts can be reused against current data or adapted when
their saved evidence supports the requested change. Result rows are not cached
for other users. Generic procedures are shared within the tenant; other eligible
procedures remain private to their owner.

## Retrieval failures

The shared Okta API client records request outcomes separately from generated
result tables. Web, CLI, Slack, Teams, and saved-query execution check these records
before accepting an answer or queuing it for reuse. A table printed after a failed
request is rejected, including an empty table; a successful empty response remains
valid. Pagination errors and reaching the pagination safety limit are failures.

GET requests retry network errors, timeouts, and server errors up to twice, in
addition to the client's existing bounded rate-limit handling. If access is denied
or temporary failures remain, the run stops with an explanatory error. Replanning
does not fix these conditions. Other retrieval failures, from newly generated or
saved scripts, allow one supervisor-led discovery/repair attempt with reuse disabled.
Failed attempts do not disable the saved query. The saved-query fallback consumes
the same repair allowance; its replacement cannot start another repair loop.

The recovery context includes up to five failed operation paths, HTTP status/error
codes, bounded sanitized service messages, and up to 16,000 characters of the failed
script. Query parameters, authorization headers and returned records are excluded
from API diagnostics. Paths may include resource identifiers and stay in the same
authorized turn. The supervisor delegates investigation; discovery can search the
catalog and test an alternative against the resource that failed. Prompts contain
no endpoint-specific recovery examples or policy-name exceptions. Unsupported
relationships must not silently become empty results or excluded resources.

The repair is capped at 300 seconds and retains normal discovery/tool budgets.
The repaired script passes normal validation and execution checks. A second failure
stops; only a successful eligible result can be admitted. Web progress shows
"Refining retrieval" and continues streaming discovery events; cumulative token
usage combines the available usage from both attempts (a specialist interrupted
by its tool budget may not return its usage). Recovery is an opportunity to investigate, not a
guarantee that another supported endpoint exists or that the model will repair it.

A subsequent identical successful request in the same execution resolves its
earlier failure. A different filter or request does not. An unresolved 404 is
conservatively treated as a retrieval failure; there is no general exemption for
missing resources or inferred recovery through a different endpoint. Explicit
result limits are retained, while an unrequested pagination safety stop is rejected.
These diagnostics cover calls through the shared client's `make_request`, not
arbitrary HTTP libraries, semantic omissions, or proof that the answer is correct.
They are correctness checks, not a security boundary against malicious scripts.

## Saving a query

Successful script runs also retain bounded source evidence (up to 16,000 characters,
with truncation marked) in their conversation result metadata. Follow-up analysis
can explain what ran without retrieving everything again. Empty executed results
remain available as evidence. This is scoped to the existing conversation, not
shared result data, and does not retroactively reconstruct scripts for old turns.
Source evidence describes the executed method; it does not certify completeness
or live freshness and is never executed by the restricted result-analysis agent.

The supervisor resolves material ambiguity before retrieval using the question and
established conversation. Its existing decision response includes a scope
interpretation and unresolved user questions; nonempty questions force clarification
before delegation or reuse. Recognizing ambiguity still depends on the model.
An empty intermediate result no longer overrides a
decision to clarify or retrieve missing requirements. Existing discovery budgets
and repeat-detection controls still apply.

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
