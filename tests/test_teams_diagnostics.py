import unittest

import httpx

from src.integrations.teams.diagnostics import failure_details


class DiagnosticsTests(unittest.TestCase):
    def test_http_status_and_frames_without_private_data(self):
        request = httpx.Request("PUT", "https://smba.trafficmanager.net/private-conversation?token=private-token")
        response = httpx.Response(400, request=request, text="private-response")
        try:
            raise httpx.HTTPStatusError("private-error", request=request, response=response)
        except httpx.HTTPStatusError as exc:
            details = failure_details(exc)
        self.assertIn("http_status=400", details)
        self.assertIn("test_http_status_and_frames_without_private_data", details)
        self.assertNotIn("private", details.replace("test_http_status_and_frames_without_private_data", "test"))

    def test_missing_filename_without_contents_or_directory(self):
        details = failure_details(FileNotFoundError(2, "private-message", "private-directory/artifacts"))
        self.assertIn("missing_file='artifacts'", details)
        self.assertNotIn("private", details)
