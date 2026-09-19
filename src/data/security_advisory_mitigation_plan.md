# Security Advisory Mitigation Plan

Date: 2026-06-14

Source of findings: repository security advisories fetched with `gh api` from the private repo advisory endpoint.

## Advisories In Scope

| GHSA | Severity | Summary | Primary Surface |
| --- | --- | --- | --- |
| GHSA-536w-42p8-3qv9 | Critical | Unauthenticated first-run admin takeover via `POST /api/auth/setup` | Bootstrap/auth |
| GHSA-r9q7-6784-7rc6 | High | Authenticated Python code execution via validator bypass | Script replay/execution |

## Executive Recommendation

The least-change package that closes both advisories is:

1. Gate first-run setup with a bootstrap secret and stop exposing the app on all interfaces by default.
2. Stop accepting browser-supplied `script_code` entirely; replay only server-owned scripts by `history_id` or artifact ID.
3. Keep validator hardening and container isolation as defense in depth, not as the primary trust boundary.

This is the smallest coherent fix because both advisories come from the same architectural problem: the server currently trusts a remote caller too early for high-impact actions.

## What The Codebase Shows Today

### 1. First-run bootstrap is unauthenticated

- `src/api/routers/auth.py` exposes `POST /setup` and only checks whether setup is already complete.
- `src/api/main.py` mounts `auth.router` without a global auth guard.
- `docker-compose.yml` publishes `8001:8001` on all interfaces.
- `Dockerfile` starts uvicorn on `0.0.0.0`.
- The frontend actively routes users to `/setup` when setup is incomplete in `src/frontend/src/router/index.js` and calls `/api/auth/setup` from `src/frontend/src/composables/useAuth.js`.

Result: a fresh instance can be claimed by any network-reachable client before the legitimate owner completes bootstrap.

### 2. Direct script execution trusts the browser too much

- `src/api/routers/react_stream.py` defines `ScriptExecuteRequest` with raw `script_code`.
- `POST /api/react/execute-script` only requires `get_current_user`, then stores client-supplied code in `active_processes` with `skip_discovery=True`.
- The same module later copies that code into `result.script_code`, validates it, writes it to `generated_scripts`, and executes it with `asyncio.create_subprocess_exec(...)`.
- `src/utils/security_config.py` still treats validation as the main control even though the input is untrusted Python source.

Result: validator bypass becomes full server-side code execution because the public API accepts code, stores it, writes it, and runs it.

### 3. The validator gap is real, but it is not the main root cause

The advisory accurately points to three weaknesses in `src/utils/security_config.py`:

- `getattr` is allowed in `ALLOWED_BUILTINS`.
- The regex rules catch direct `__import__(...)` but not string-based access paths.
- The AST call checker does not treat a nested `ast.Call` used as the callee as a violation.

Those are real bugs, but fixing only those bugs still leaves the product in a fragile state because a public endpoint would continue to accept executable Python from an untrusted client.

### 4. The same execution model exists outside the web UI

- `src/integrations/slack/slack_app.py` validates scripts with the same `validate_generated_code(...)` function.
- The same Slack module writes scripts to disk and executes them with a subprocess.

Any holistic fix should therefore cover all replay/direct-execution surfaces, not just the browser route.

### 5. There is already a lower-risk reuse point for replay

- `src/api/routers/history.py` already has an `/{history_id}/execute` route stub that loads a saved script for the current user.

That is the best low-change pivot away from browser-supplied code: use server-owned references instead of client-supplied Python.

## Least-Change Remediation Plan

### Phase 0: Immediate Operational Controls

These can be applied before any code change:

1. Restrict port `8001` to localhost, VPN, or an allowlisted reverse proxy until initial setup is complete.
2. Temporarily block `POST /api/react/execute-script` at the proxy or ingress layer.
3. Treat any internet-exposed fresh instance as potentially compromised and rotate `OKTA_API_TOKEN`, `JWT_SECRET_KEY`, and any other environment secrets.
4. Assume any exposed beta instance that allowed replay of saved scripts should be reviewed for suspicious sessions and unexpected admin creation.

These steps reduce immediate risk, but they should not be the final fix.

### Phase 1: Minimal Code Changes That Actually Close The Advisories

#### A. Lock down first-run setup

Recommended change set:

1. Add a required bootstrap secret such as `INITIAL_SETUP_TOKEN` or `BOOTSTRAP_SETUP_TOKEN` in `src/config/settings.py`.
2. Require that token on `POST /api/auth/setup` while `check_setup_completed(...)` is still false.
3. Reject setup requests when the token is missing or wrong.
4. Keep `GET /api/auth/setup-status` so the frontend can still decide whether to render the setup screen.
5. Change the default deployment to bind the app to localhost only, for example `127.0.0.1:8001:8001`, and let operators opt into wider exposure explicitly.

Why this is the least-change fix:

- It preserves the existing setup UX.
- It requires only a small settings addition plus a single route check.
- It does not require a new auth system.
- It removes the dangerous assumption that reachability equals legitimacy.

Important note:

- CORS is not a security control here. The advisory is correct that non-browser clients ignore it.
- IP allowlisting by itself is useful as an extra deployment guard, but a bootstrap token should be the primary code-level control.

#### B. Remove untrusted script submission from the public API

Recommended change set:

1. Stop accepting `script_code` from the browser on `POST /api/react/execute-script`.
2. Replace the request contract with a server-owned reference such as `history_id`, `turn_id`, or an artifact ID.
3. Load the stored script server-side after verifying ownership.
4. Insert the loaded script into `active_processes` internally and continue using the existing SSE execution flow.

The best low-change path is to reuse the existing saved-script flow in `src/api/routers/history.py` instead of building a new execution concept.

If the team wants the absolute fastest safe patch, the fallback option is even simpler:

1. Return `403 Forbidden` from `POST /api/react/execute-script`.
2. Hide or disable the frontend replay button.
3. Restore replay later using a server-owned `history_id` path.

Why this is the real fix for the RCE advisory:

- It removes the unsafe trust boundary instead of trying to perfectly parse hostile Python.
- It preserves the normal query flow, which already originates from server-generated code rather than client-supplied code.
- It makes validator bypasses materially less valuable because an attacker no longer controls the code payload directly from the browser.

#### C. Require admin for any remaining direct execution or replay surface

If any endpoint still exists for direct script execution, make it admin-only.

The repo already has a reusable dependency for this in `src/core/security/dependencies.py`:

- `get_current_user(...)`
- `get_current_active_admin(...)`

Recommendation:

1. Normal query execution should continue to require only authenticated access.
2. Any replay, debug, or direct-execution path should require `get_current_active_admin(...)`.
3. Add a feature flag such as `ENABLE_DIRECT_SCRIPT_EXECUTION=false` by default if any such path must remain.

This is a small code change with a large risk reduction.

### Phase 2: Defense In Depth After The Trust Boundary Is Fixed

These changes are still worth doing, but they should not be treated as the primary fix.

#### A. Tighten the validator

Recommended updates in `src/utils/security_config.py`:

1. Remove `getattr` from `ALLOWED_BUILTINS`.
2. Reject any `ast.Call` used as the callee of another call.
3. Reject runtime escape names such as `__builtins__`, `__loader__`, and `__spec__`.
4. Reject suspicious dunder string constants where practical.
5. Keep the existing parse-first behavior that already avoids corrupting valid code before AST parsing.

This closes the reported bypass class and improves the safety of server-generated scripts and Slack replay.

#### B. Apply the same rules to Slack replay

The Slack path uses the same validator and the same basic write-and-exec model. Once the web fix is made, mirror the same policy in `src/integrations/slack/slack_app.py`:

1. Replay only server-owned scripts.
2. Restrict who can trigger replay.
3. Keep the validator changes in sync.

Without this, the web advisory can be closed while the same design remains elsewhere.

#### C. Reduce blast radius if code execution is found again

Current deployments appear to run the application process as root inside the container because the Dockerfile does not set a non-root `USER`.

Recommended hardening:

1. Run the app as a non-root user.
2. Grant write access only to runtime directories such as `sqlite_db`, `chat_sessions`, `logs`, `certs`, and `generated_scripts`.
3. Consider `no-new-privileges`, dropped Linux capabilities, and a read-only root filesystem where compatible.
4. Treat this as containment only, not as a substitute for removing the public code-execution trust boundary.

## Changes I Would Not Recommend As The Primary Fix

1. Expanding the regex denylist and leaving browser-supplied `script_code` in place.
2. Relying on CORS or cookie settings to protect `POST /api/auth/setup`.
3. Keeping direct execution public and attempting to build a perfect Python sandbox in-process.
4. Limiting fixes to the web router while leaving the Slack replay model unchanged.

Those approaches either keep the root problem intact or create a high-maintenance security posture.

## Suggested Implementation Order

### Option 1: Fastest Safe Patch

1. Require a bootstrap token for `POST /api/auth/setup`.
2. Bind Docker/Compose to localhost by default.
3. Disable `POST /api/react/execute-script` completely.
4. Ship validator hardening and non-root container as follow-up hardening.

Pros:

- Very small code delta.
- Fastest path to closing both advisories.

Tradeoff:

- Browser replay of saved scripts is temporarily removed.

### Option 2: Best Low-Change Long-Term Patch

1. Require a bootstrap token for `POST /api/auth/setup`.
2. Bind Docker/Compose to localhost by default.
3. Replace browser-supplied `script_code` with `history_id` or artifact-based replay.
4. Make replay admin-only if the feature is primarily operational.
5. Tighten the validator and apply the same policy to Slack.
6. Run the container as non-root.

Pros:

- Closes the advisories without removing replay functionality.
- Reuses existing server-side history structures.
- Keeps the change set contained to a few well-defined files.

Tradeoff:

- Slightly more frontend and router work than a hard disable.

## Validation Checklist After The Fix

1. Fresh instance: `POST /api/auth/setup` without the bootstrap token returns `403`.
2. Fresh instance: `POST /api/auth/setup` with the correct token succeeds once.
3. Post-setup: any further setup attempt is rejected.
4. `POST /api/react/execute-script` no longer accepts browser-supplied Python.
5. Saved-script replay works only through a server-owned reference and ownership check, or is intentionally disabled.
6. The EQSTLab RCE payload is rejected before execution and cannot reach a subprocess sink from the browser path.
7. Slack replay follows the same policy as the web path.
8. The container process no longer runs as root.

## Files Most Likely To Change

- `src/config/settings.py`
- `src/api/routers/auth.py`
- `src/api/routers/react_stream.py`
- `src/api/routers/history.py`
- `src/core/security/dependencies.py`
- `src/utils/security_config.py`
- `src/integrations/slack/slack_app.py`
- `src/frontend/src/composables/useAuth.js`
- `src/frontend/src/composables/useReactStream.js`
- `docker-compose.yml`
- `Dockerfile`

## Fork Handoff Package

This section is intended to be copied into the temporary private fork so implementation can start immediately.

### Recommended Working Strategy

Use Option 1 first unless replay preservation is required immediately.

Reason:

- It closes both advisories with the fewest moving parts.
- It is easier to validate privately.
- It reduces the risk of partial fixes that leave the browser script-execution trust boundary in place.

That means the first private patch should do the following:

1. Add a bootstrap token requirement to `POST /api/auth/setup`.
2. Change default deployment exposure from all interfaces to localhost-only.
3. Disable `POST /api/react/execute-script` for browser-supplied code.
4. Harden the validator enough to close the reported bypass pattern.
5. Run the container as a non-root user if that can be done without destabilizing startup.

### Exact Implementation Tasks

#### Task 1: Protect initial setup with a bootstrap token

Target files:

- `src/config/settings.py`
- `src/api/routers/auth.py`
- optionally frontend text in `src/frontend/src/composables/useAuth.js` or setup UI components

Required behavior:

1. Add a new environment-backed setting such as `INITIAL_SETUP_TOKEN`.
2. Require the token only while setup is incomplete.
3. Reject missing or incorrect token with `403 Forbidden`.
4. Keep the existing one-time `is_setup` check.
5. Do not weaken existing password validation or cookie issuance logic.

Preferred request shape:

- Either extend the setup JSON body with a token field,
- or accept a header such as `X-Setup-Token`.

Lowest-change preference:

- A header is slightly less invasive to the current request model.
- A body field is easier if the frontend setup page must provide it interactively.

#### Task 2: Make default deployment localhost-only

Target files:

- `docker-compose.yml`
- `Dockerfile`
- any deployment docs that explicitly describe the default bind behavior

Required behavior:

1. Change Compose port publication from `8001:8001` to `127.0.0.1:8001:8001`.
2. If practical, make broader exposure opt-in through deployment configuration rather than default behavior.
3. Keep HTTPS and the existing health check behavior intact.

Note:

- The internal uvicorn bind may remain `0.0.0.0` if Compose or container publishing becomes localhost-only.
- If you change both layers, verify that local development still works.

#### Task 3: Remove browser-supplied script execution

Target files:

- `src/api/routers/react_stream.py`
- `src/frontend/src/composables/useReactStream.js`
- any UI surface that triggers saved-script replay

Required behavior for the fastest safe patch:

1. `POST /api/react/execute-script` must stop accepting arbitrary `script_code` from the browser.
2. The endpoint should return `403` or `400` with a clear message that client-supplied script execution is disabled.
3. The frontend should stop calling that path for replay.

If preserving replay in the same patch:

1. Replace browser-supplied `script_code` with a server-owned reference such as `history_id`.
2. Load the stored script server-side.
3. Verify the authenticated user owns the history entry.
4. Continue using the existing SSE execution pipeline after server-side lookup.

Important constraint:

- Do not keep the current API contract and attempt to rely only on improved validation.

#### Task 4: Harden the validator

Target file:

- `src/utils/security_config.py`

Required behavior:

1. Remove `getattr` from `ALLOWED_BUILTINS` for generated code validation.
2. Treat nested dynamic call targets as violations.
3. Block direct use of runtime escape names such as `__builtins__`.
4. Preserve the current parse-first-then-preprocess behavior.

Goal:

- Even after the public browser path is removed, server-generated or replayed scripts should reject the bypass family described in the advisory.

#### Task 5: Align Slack replay policy

Target file:

- `src/integrations/slack/slack_app.py`

Required behavior:

1. Reuse the hardened validator behavior.
2. Ensure any replay path is treated as privileged or server-owned.
3. Do not leave Slack as an easier equivalent execution path after the web fix.

#### Task 6: Reduce container blast radius

Target file:

- `Dockerfile`

Required behavior:

1. Create and run as a non-root app user.
2. Ensure runtime directories remain writable.
3. Verify certificate generation, logs, DB, and generated scripts still work.

This is secondary to the trust-boundary fixes, but it is still a good same-stream hardening change if it stays low-risk.

### Non-Goals For The First Private Patch

Do not let the patch scope drift into these areas unless they are required to make the security fix work:

1. broad auth redesign
2. frontend UI refreshes unrelated to setup or replay
3. large refactors of orchestration flow
4. changes to normal query generation behavior beyond what is needed to remove direct browser script replay
5. adding a complicated sandbox runtime

### Acceptance Criteria

The patch is not ready until all of these are true:

1. A fresh instance cannot be claimed without the bootstrap token.
2. A fresh instance can still be initialized successfully with the correct token.
3. Browser clients cannot submit raw Python for execution.
4. The advisory bypass payload cannot reach subprocess execution from the browser path.
5. Slack does not remain an equivalent unguarded replay path.
6. Default local deployment is no longer exposed on all interfaces.
7. The app still starts successfully with the expected local dev workflow.

### Suggested Test Cases

#### Setup takeover tests

1. Start from an empty database.
2. Call `GET /api/auth/setup-status` and confirm setup is required.
3. Call `POST /api/auth/setup` without the token and expect rejection.
4. Call `POST /api/auth/setup` with the correct token and expect success.
5. Call `POST /api/auth/setup` a second time and expect rejection.

#### Script execution tests

1. Log in as a normal authenticated user.
2. Call `POST /api/react/execute-script` with raw `script_code`.
3. Confirm the request is rejected before any execution starts.
4. If replay is preserved through `history_id`, confirm the server can execute only the stored script owned by that user.

#### Validator tests

Use variants of the advisory payload to verify rejection of:

1. `getattr(__builtins__, "__import__")`
2. nested dynamic call targets like `getattr(mod, "popen")("id")`
3. direct references to `__builtins__`

#### Container/runtime tests

1. Build the image.
2. Start the container.
3. Confirm `/health` works.
4. Confirm the process is not running as root.

### Practical File Order For Implementation

Recommended coding order in the private fork:

1. `src/config/settings.py`
2. `src/api/routers/auth.py`
3. `docker-compose.yml`
4. `src/api/routers/react_stream.py`
5. `src/frontend/src/composables/useReactStream.js`
6. `src/utils/security_config.py`
7. `src/integrations/slack/slack_app.py`
8. `Dockerfile`

This order keeps the riskier execution-path changes after the simple setup and deployment controls are in place.

### Notes For The AI Agent Working In The Fork

The agent should be told the following explicitly:

1. Work only in the private fork clone, not the public repo clone.
2. Keep changes minimal and fix the root trust-boundary issues first.
3. Prefer disabling client-supplied script execution over preserving it with weak validation.
4. Reuse existing admin and auth dependencies rather than inventing a parallel permission system.
5. Do not request a CVE, publish advisories, or prepare public-facing disclosure text during coding.
6. Do not create broad documentation sets; update only what is needed for secure deployment and setup.

### Copy-Paste Starter Prompt For The Fork Agent

Use this prompt in the private fork workspace:

```text
We are fixing two private GitHub security advisories for this repo in the temporary private fork.

Scope:
1. GHSA-536w-42p8-3qv9: unauthenticated first-run admin takeover via POST /api/auth/setup.
2. GHSA-r9q7-6784-7rc6: authenticated Python code execution via validator bypass and browser-supplied script replay.

Constraints:
1. Make the smallest coherent patch set that closes both advisories.
2. Do not redesign unrelated architecture.
3. Preserve normal query flow where possible.
4. Prefer disabling unsafe replay over preserving it.
5. Work only in this private fork.

Required changes:
1. Add a bootstrap token requirement for initial setup.
2. Change default deployment exposure to localhost-only.
3. Remove or disable browser-supplied script_code execution.
4. Harden generated code validation against the reported getattr/__builtins__/nested-call bypasses.
5. Ensure Slack replay does not remain an easier equivalent execution path.
6. If feasible with low risk, run the container as non-root.

Validation targets:
1. Fresh instance setup fails without token and succeeds with it once.
2. POST /api/react/execute-script no longer executes browser-supplied Python.
3. The reported RCE payload is rejected before execution.
4. Default local deployment is not exposed on all interfaces.
5. App startup and health checks still work.

Prefer small focused edits and run narrow validation after each substantive change.
```

## Bottom Line

If the goal is the smallest set of changes that holistically fixes both advisories, do not spend the first PR trying to perfect Python validation. The best first PR is to remove trust in remote callers for privileged bootstrap and code execution:

1. bootstrap token for first-run admin creation,
2. localhost-by-default exposure,
3. no browser-supplied `script_code`, and
4. admin-only or server-owned replay for any remaining execution path.

That closes the two reported advisories at the architectural seam that made them possible.