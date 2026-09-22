"""Offline checks for the catalogs consumed by API discovery and activity labels."""
import json
from pathlib import Path
import re
import unittest


SCHEMAS = Path(__file__).resolve().parents[1] / "src" / "data" / "schemas"


class EndpointCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.read_only = json.loads(
            (SCHEMAS / "Okta_API_entitity_endpoint_reference_GET_ONLY.json").read_text(encoding="utf-8")
        )
        cls.full = json.loads(
            (SCHEMAS / "Okta_API_entitity_endpoint_reference.json").read_text(encoding="utf-8")
        )
        cls.operations = json.loads(
            (SCHEMAS / "lightweight_onereact.json").read_text(encoding="utf-8")
        )["operations"]

    def test_discovery_operations_are_unique_and_resolve_to_read_only_endpoints(self):
        endpoints = self.read_only["endpoints"]
        identities = [e["id"] for e in endpoints]
        operations = [f'{e["entity"]}.{e["operation"]}' for e in endpoints]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(operations), len(set(operations)))
        self.assertEqual(set(operations), set(self.operations))
        self.assertTrue(all(e["method"] == "GET" for e in endpoints))

    def test_parallel_catalogs_agree_on_read_only_contracts_and_documentation(self):
        # The source catalog uses :param; the runtime catalog uses {param}.
        # Some inherited parameter aliases differ, so compare route structure.
        def route(path):
            return re.sub(r"\{[^}]+\}|:[^/]+", "{}", path)

        full = {(e["method"], route(e["url_pattern"])): e for e in self.full["endpoints"]}
        for endpoint in self.read_only["endpoints"]:
            with self.subTest(endpoint=endpoint["id"]):
                counterpart = full[endpoint["method"], route(endpoint["url_pattern"])]
                for key in ("id", "entity", "operation", "name", "description", "notes", "parameters"):
                    self.assertEqual(endpoint[key], counterpart[key], key)

    def test_path_parameters_are_required_and_query_options_do_not_overlap(self):
        for endpoint in self.read_only["endpoints"]:
            with self.subTest(endpoint=endpoint["id"]):
                required = endpoint["parameters"]["required"]
                optional = endpoint["parameters"]["optional"]
                path_parameters = set(re.findall(r"\{([^}]+)\}", endpoint["url_pattern"]))
                self.assertTrue(path_parameters.issubset(required))
                self.assertFalse(set(required) & set(optional))
                self.assertEqual(len(required + optional), len(set(required + optional)))

    def test_resolution_hints_reference_known_endpoints_without_cycles(self):
        graph = {e["id"]: e.get("depends_on", []) for e in self.read_only["endpoints"]}
        visited = set()

        def visit(node, ancestors):
            self.assertIn(node, graph, "Unknown dependency")
            self.assertNotIn(node, ancestors, "Circular endpoint dependency")
            if node in visited:
                return
            for dependency in graph[node]:
                visit(dependency, ancestors | {node})
            visited.add(node)

        for node in graph:
            visit(node, set())

    def test_entity_index_matches_available_operations(self):
        for entity, metadata in self.read_only["entity_summary"].items():
            entries = [e for e in self.read_only["endpoints"] if e["entity"] == entity]
            with self.subTest(entity=entity):
                self.assertEqual(metadata["endpoint_count"], len(entries))
                self.assertEqual(set(metadata["operations"]), {e["operation"] for e in entries})
                self.assertEqual(set(metadata["methods"]), {e["method"] for e in entries})


if __name__ == "__main__":
    unittest.main()
