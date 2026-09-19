"""Single-resource fields must survive collection response normalization."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.core.okta.client.base_okta_api_client import OktaAPIClient


class ResponseNormalizationTests(unittest.TestCase):
    def normalize(self, value):
        return OktaAPIClient._normalize_okta_response(SimpleNamespace(logger=Mock()), value)

    def test_resource_with_array_fields_preserves_whole_object(self):
        for resource in (
            {"id": "group-1", "objectClass": ["okta:user_group"], "profile": {"name": "Everyone"}},
            {"id": "key-1", "x5c": ["fixture-certificate"], "expiresAt": "2030-01-01"},
            {"id": "policy-1", "_embedded": {"rules": [{"id": "rule-1"}]}, "conditions": {"fixture": True}},
        ):
            with self.subTest(resource=resource["id"]):
                result = self.normalize(resource)
                self.assertEqual(result, [resource])
                self.assertIs(result[0], resource)

    def test_collection_wrappers_still_unwrap(self):
        rows = [{"id": "fixture"}]
        for wrapper in (
            rows, {"value": rows}, {"results": rows}, {"items": rows}, {"data": rows},
            {"_embedded": {"items": rows}}, {"custom_collection": rows},
        ):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(self.normalize(wrapper), rows)

    def test_empty_and_primitive_responses_are_preserved(self):
        for source, expected in ((None, []), ([], []), ({"items": []}, []),
                                 ({"totalCount": 0}, []), ("fixture", "fixture")):
            with self.subTest(source=source):
                self.assertEqual(self.normalize(source), expected)


if __name__ == "__main__":
    unittest.main()
