# Read-only endpoint catalog

`Okta_API_entitity_endpoint_reference_GET_ONLY.json` supplies the API discovery
agent with supported operations, readable names, descriptions, parameters, and
notes. Endpoint `name` values also label API request activity. The corresponding
GET entries in `Okta_API_entitity_endpoint_reference.json` carry the same wording.
The full catalog retains its legacy `:parameter` path notation; the runtime
catalog uses `{parameter}`. `lightweight_onereact.json` indexes stable operation
names rather than detailed documentation.

## Writing conventions

- Give each endpoint a short, specific English name: what the operation reads or
  lists. Do not copy one generic title across unrelated operations.
- Describe what it actually returns and the question it helps answer. Distinguish
  configuration, assignment, observed activity, and effective access.
- In notes, explain parameter locations, supported filtering/expansion, response
  shape, identifier relationships, pagination, and important interpretation limits.
- Keep identifiers and enum values exact. Use plain English around them. Do not
  include tenant IDs, fixed dates, or worked user queries that a model might copy.
- An endpoint description is retrieval guidance, not a final answer to the user.
  Do not claim success, completeness, or effective permissions from configuration
  alone. Distinguish unavailable data from successful empty results.
- `depends_on` contains identifier-resolution hints. An already known ID does not
  require repeating the parent lookup. Collection operations must not depend on
  their own child/detail operations.
- Keep the two catalogs synchronized when editing names, descriptions, notes, or
  supported parameters. Preserve stable operation IDs and unrelated write entries.

## September 22, 2026 review

Reviewed all 107 runtime GET endpoints: seven policy endpoints followed by the
remaining 100. The review used Okta's
[management OpenAPI specification at revision 6bef7392](https://github.com/okta/okta-management-openapi-spec/blob/6bef7392c9dc2fec180c799984fd61749a8eb33f/dist/current/management-minimal.yaml),
including parameter definitions, response schemas, and examples. Policy subtype
guidance additionally uses the
[account management policy guide](https://developer.okta.com/docs/guides/okta-account-management-policy/main/)
and [policy concepts](https://developer.okta.com/docs/concepts/policies/).
Endpoint notes record their sources. These are reviewed contracts, not guarantees
that every feature is enabled in every tenant.

Significant corrections include:

- Application launch links, user assignments, OAuth grants, and administrator
  targets represent different relationships. App-user assignments can be direct
  or group-based.
- Group `search` supports pagination; `q` does not. Group `expand=app` describes a
  source app, not the group's assigned applications.
- Certificate/key dates differ from app creation dates. OAuth client secrets are
  not documented as metadata-only responses.
- Device lifecycle state does not establish compliance. Authenticator
  configuration, enrollment options, enrolled factors, and successful use differ.
- Empty standard-role target lists can represent unscoped roles. Resource-set and
  custom-role collections use named response wrappers rather than bare arrays.
- System Log ordering defaults to ascending. Retained event evidence, bounded
  queries, and polling must be interpreted separately.
- First-party app settings use the documented `admin-console` key. Previously
  omitted optional parameters now include resource-set pagination and user field
  projection, among other supported options.

The current OpenAPI schema for listing authenticator enrollments references a
singleton, but its collection example is an array. The endpoint notes disclose
that discrepancy and require checking the actual response rather than asserting
the singleton shape is correct.

## Validation

From the repository root:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_endpoint_catalog tests.test_api_test_progress -q
```

These offline checks verify operation/index alignment, read-only methods,
cross-catalog consistency, parameter integrity, dependency resolution, and API
activity-event behavior. They do not establish live access to every endpoint or
measure model selection accuracy. Documentation changes require fresh discovery
to evaluate their effect; a previously saved script may bypass endpoint discovery.
