"""Opt-in model evaluation with synthetic Okta responses; no tenant requests.

Run from the repository root:
    python tests/eval_api_discovery_prompt.py --baseline-dir logs/api-prompt-review/before --output logs/api-prompt-review/baseline.json
    python tests/eval_api_discovery_prompt.py --output logs/api-prompt-review/refined.json

Uses the configured coding model and its credentials from .env (incurs model
usage). This evaluates API discovery, not final
synthesis or the complete orchestrator. Nothing here validates a security sandbox.
"""

import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = {
    "users": "List all users along with their creation dates",
    "api_only": "List all users using API only",
    "roles": "Show the roles for those users",
    "saml": "Find the SAML certificate expiry date for all active SAML applications using API only",
    "empty_logs": "List sign-in events from the past 24 hours using API only",
    "denied": "List all users using API only",
}


class FixtureClient:
    """An in-memory fixture, never a network client."""

    base_url = "https://prompt-eval.okta.com"

    def __init__(self, case):
        self.case = case
        self.test_mode = False
        self.calls = []

    async def make_request(self, endpoint, method="GET", params=None, **kwargs):
        from urllib.parse import urlsplit

        self.calls.append({"endpoint": endpoint, "method": method, "params": params})
        if method != "GET" or not endpoint.startswith("/api/v1/"):
            raise ValueError("Fixture permits only relative /api/v1/ GET requests")
        path = urlsplit(endpoint).path
        if self.case == "denied":
            return {"status": "error", "status_code": 403, "error": "E0000006: Access forbidden; insufficient permissions"}
        if path == "/api/v1/users":
            data = [{"id": f"00u_fixture_{i}", "status": "ACTIVE", "created": "2025-01-01T00:00:00Z",
                     "profile": {"login": f"user{i}@fixture.invalid", "email": f"user{i}@fixture.invalid"}}
                    for i in (1, 2, 3)]
        elif path in [f"/api/v1/users/00u_fixture_{i}/roles" for i in (1, 2)]:
            data = [{"id": "role_fixture", "type": "READ_ONLY_ADMIN", "status": "ACTIVE"}]
        elif path == "/api/v1/apps":
            data = [{"id": "0oa_fixture", "label": "Fixture SAML app", "name": "fixture",
                     "status": "ACTIVE", "signOnMode": "SAML_2_0",
                     "credentials": {"signing": {"kid": "current_fixture_key"}}}]
        elif path == "/api/v1/apps/0oa_fixture/credentials/keys":
            data = [{"kid": "current_fixture_key", "expiresAt": "2030-06-01T00:00:00Z"},
                    {"kid": "older_fixture_key", "expiresAt": "2029-06-01T00:00:00Z"}]
        elif path == "/api/v1/logs":
            data = []
        else:
            return {"status": "error", "status_code": 404, "error": "Endpoint is outside this fixture scenario"}
        return {"status": "success", "data": deepcopy(data)}


def assess(case, output, client, artifacts):
    paths = [call["endpoint"].split("?")[0] for call in client.calls]
    checks = {"no_sql_handback": not output.needs_sql,
              "get_only": all(call["method"] == "GET" for call in client.calls)}
    if case in {"users", "api_only"}:
        checks.update(success=output.success, fetched_users="/api/v1/users" in paths)
    elif case == "roles":
        expected = {f"/api/v1/users/00u_fixture_{i}/roles" for i in (1, 2)}
        checks.update(success=output.success, preserved_population=set(paths) == expected)
    elif case == "saml":
        apps = "/api/v1/apps"
        keys = "/api/v1/apps/0oa_fixture/credentials/keys"
        checks.update(success=output.success,
                      dependency_order=apps in paths and keys in paths and paths.index(apps) < paths.index(keys))
    elif case == "empty_logs":
        checks.update(empty_reported=not output.success and bool(output.error),
                      queried_logs=paths == ["/api/v1/logs"],
                      kept_filter=bool(client.calls) and all("filter" in json.dumps(c) for c in client.calls),
                      no_success_artifacts=not artifacts)
    elif case == "denied":
        checks.update(failure_reported=not output.success and bool(output.error),
                      no_retry=len(client.calls) == 1, no_success_artifacts=not artifacts)
    if case not in {"empty_logs", "denied"}:
        checks["saved_code_and_data"] = bool(artifacts) and all(a.get("api_code") and a.get("content") for a in artifacts)
    return checks


async def evaluate(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ["OKTA_CLIENT_ORGURL"] = FixtureClient.base_url
    os.environ["OKTA_API_TOKEN"] = "synthetic-fixture-token"

    if args.baseline_dir:
        spec = importlib.util.spec_from_file_location("api_discovery_prompt_baseline", args.baseline_dir / "api_discovery_agent.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    else:
        from src.core.agents import api_discovery_agent as module
    from src.core.security import network_security

    # Application imports may reload .env. Reapply synthetic settings afterwards.
    os.environ["OKTA_CLIENT_ORGURL"] = FixtureClient.base_url
    os.environ["OKTA_API_TOKEN"] = "synthetic-fixture-token"
    network_security._network_validator = network_security.NetworkSecurityValidator()

    catalog = json.loads((ROOT / "src/data/schemas/Okta_API_entitity_endpoint_reference_GET_ONLY.json").read_text())["endpoints"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "provider": os.getenv("AI_PROVIDER"),
        "model": module.api_discovery_agent.model.model_name,
        "prompt_sha256": hashlib.sha256(module.PROMPT_FILE.read_bytes()).hexdigest(),
        "agent_source_sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
        "scope": "Real configured model, synthetic Okta responses; API discovery only",
        "cases": [],
    }
    for case in args.case or CASES:
        client = FixtureClient(case)
        tools = []

        async def on_tool(event):
            tools.append(event.get("tool_name"))

        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix=f"{case}-", dir=args.output.parent) as tmp:
            deps = module.APIDiscoveryDeps(
                correlation_id=f"prompt-eval-{case}", artifacts_file=Path(tmp) / "artifacts.json",
                endpoints=catalog, okta_client=client, tool_call_callback=on_tool,
            )
            if case == "roles":
                deps.sql_found_data = ["users"]
                deps.sql_needs_api = ["roles"]
                deps.sql_reasoning = "SQL found the two requested users, 00u_fixture_1 and 00u_fixture_2. Fetch their roles only."
                deps.sql_discovered_data = json.dumps({"result_set_refs": ["fixture-users"],
                    "key_columns": ["okta_id"], "sample_rows": [{"okta_id": "00u_fixture_1"}, {"okta_id": "00u_fixture_2"}]})
            output, usage = await asyncio.wait_for(module.execute_api_discovery(CASES[case], deps), timeout=180)
            checks = assess(case, output, client, deps.artifacts)
            report["cases"].append({"case": case, "checks": checks, "passed": all(checks.values()),
                                    "output": output.model_dump(), "requests": client.calls, "tools": tools,
                                    "artifacts": deps.artifacts,
                                    "usage": {k: getattr(usage, k, None) for k in ("requests", "input_tokens", "output_tokens")}})
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"EVAL {case}: {'PASS' if all(checks.values()) else 'FAIL'} {checks}", flush=True)
    return 0 if all(case["passed"] for case in report["cases"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, help="Snapshot containing api_discovery_agent.py and prompts/api_discovery_prompt.txt")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    os.chdir(ROOT)
    raise SystemExit(asyncio.run(evaluate(arguments)))
