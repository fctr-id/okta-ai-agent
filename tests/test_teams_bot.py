"""Offline transport/access tests. No live Graph, Teams, Okta or model requests."""
import asyncio
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from src.integrations.teams.auth import AccessUnavailable, GroupAuthorizer, Sender, authenticated_sender
from src.integrations.teams.config import TeamsConfig
from src.integrations.teams.formatters import MAX_CARD_BYTES, result_card
from src.integrations.teams.runtime import parse_output
from src.integrations.teams.store import InboxFull, RequestStore
from src.integrations.teams.teams_app import TeamsBot

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
GROUP = "44444444-4444-4444-4444-444444444444"
SERVICE = "https://smba.trafficmanager.net/amer/"
ISSUER = "https://api.botframework.com"


def config(**kwargs):
    return TeamsConfig(tenant_id=TENANT, client_id=CLIENT, client_secret="test-not-a-secret",
                       allowed_group_ids=GROUP, **kwargs)


def activity(**kwargs):
    return {"type": "message", "id": "activity1", "channelId": "msteams", "serviceUrl": SERVICE,
            "from": {"id": "teams-user", "aadObjectId": USER, "role": "user"},
            "recipient": {"id": "bot", "role": "bot"},
            "conversation": {"id": "conversation1", "conversationType": "personal", "tenantId": TENANT},
            "channelData": {"tenant": {"id": TENANT}}, "text": "List all users", **kwargs}


def job(**kwargs):
    return {"id": "55555555-5555-5555-5555-555555555555", "tenant": TENANT, "user": USER, "query": "List all users",
            "conversation": "conversation1", "service_url": SERVICE, "command": 0,
            "created": time.time(), **kwargs}


class ConfigAndEnvelopeTests(unittest.TestCase):
    def test_invalid_or_empty_groups_fail_closed(self):
        for groups in ("", " ", GROUP + ",", "everyone"):
            with self.subTest(groups=groups), self.assertRaises(ValidationError):
                TeamsConfig(tenant_id=TENANT, client_id=CLIENT, client_secret="test", allowed_group_ids=groups)

    def test_groups_are_deduplicated_and_secret_is_redacted(self):
        cfg = TeamsConfig(tenant_id=TENANT, client_id=CLIENT, client_secret="private-value",
                          allowed_group_ids=f" {GROUP},{GROUP}")
        self.assertEqual(cfg.group_ids, [GROUP])
        self.assertNotIn("private-value", repr(cfg))

    def test_retention_is_bounded_and_enabled_by_default(self):
        self.assertEqual(config().session_retention_hours, 24)
        for hours in (0, -1, 8761):
            with self.assertRaises(ValidationError):
                TeamsConfig(tenant_id=TENANT, client_id=CLIENT, client_secret="fixture",
                            allowed_group_ids=GROUP, session_retention_hours=hours)

    def test_only_correct_tenant_personal_connector_sender(self):
        valid = activity()
        self.assertEqual(authenticated_sender(valid, ISSUER, config()).user, USER)
        cases = []
        for mutate in (
            lambda b: b["channelData"]["tenant"].update(id=CLIENT),
            lambda b: b["conversation"].update(conversationType="groupChat"),
            lambda b: b["conversation"].update(tenantId=CLIENT),
            lambda b: b["from"].pop("aadObjectId"),
            lambda b: b.update(channelId="webchat"),
            lambda b: b.update(serviceUrl="https://evil.example/"),
            lambda b: b.update(serviceUrl="http://smba.trafficmanager.net/"),
            lambda b: b.update(serviceUrl="https://smba.trafficmanager.net.evil.example/"),
        ):
            invalid = copy.deepcopy(valid)
            mutate(invalid)
            cases.append(invalid)
        for invalid in cases:
            with self.subTest(body=invalid), self.assertRaises(ValueError):
                authenticated_sender(invalid, ISSUER, config())
        with self.assertRaises(ValueError):
            authenticated_sender(valid, f"https://sts.windows.net/{TENANT}/", config())

    def test_preview_size_and_untrusted_markup(self):
        result = {"display_type": "table", "results": [{"email": "<at>Everyone</at> [click](https://evil.test)",
                  "data": "😃" * 500, "id": i, "status": "ACTIVE", "other": "hidden"} for i in range(320)]}
        card = result_card("All users", result)
        serialized = json.dumps(card, ensure_ascii=False)
        self.assertLess(len(serialized.encode("utf-16-le")), MAX_CARD_BYTES)
        table = next(b for b in card["body"] if b["type"] == "Table")
        self.assertEqual(len(table["rows"]), 11)  # Header plus ten result rows.
        self.assertIn("320 records retrieved", serialized)
        self.assertNotIn("<at>", serialized)
        self.assertNotIn('"url"', serialized)
        self.assertIn("Preview only", serialized)

    def test_table_header_objects_match_data_and_keep_older_client_fallback(self):
        from microsoft_teams.cards import AdaptiveCard
        for row in ({"email": "fixture@example.test", "status": "ACTIVE"}, ["fixture@example.test", "ACTIVE"]):
            card = result_card("All users", {"display_type": "table", "headers": [
                {"value": "email", "text": "Email", "sortable": True},
                {"key": "status", "title": "Status"},
            ], "results": [row]})
            card = AdaptiveCard.model_validate(card).model_dump(by_alias=True, exclude_none=True)
            table = next(b for b in card["body"] if b["type"] == "Table")
            self.assertEqual([c["items"][0]["text"] for c in table["rows"][0]["cells"]], ["Email", "Status"])
            self.assertEqual([c["items"][0]["text"] for c in table["rows"][1]["cells"]], ["fixture@example.test", "ACTIVE"])
            self.assertEqual(table["fallback"]["items"][1]["columns"][0]["items"][0]["text"], "fixture@example.test")
            self.assertNotIn("sortable", json.dumps(card))

    def test_clarify_and_partial_are_not_completed(self):
        for outcome, label in (("clarify", "Clarification needed"), ("degraded_success", "Partial results")):
            text = json.dumps(result_card("query", {"outcome": outcome, "content": "Need details"}))
            self.assertIn(label, text)
            self.assertNotIn('"text": "Completed"', text)

    def test_parser_rejects_invalid_output_instead_of_empty_success(self):
        for output in ("Traceback", "QUERY RESULTS\nnot json", "QUERY RESULTS\n{}"):
            with self.assertRaises(ValueError):
                parse_output(output)
        self.assertEqual(parse_output('QUERY RESULTS\n====\n[]\n====')["count"], 0)
        self.assertEqual(parse_output('QUERY RESULTS\n{"data": [{"x": 1}]}')["count"], 1)


class GroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_batches_and_no_membership_cache(self):
        groups = [str(UUID(int=i + 1)) for i in range(22)]
        cfg = TeamsConfig(tenant_id=TENANT, client_id=CLIENT, client_secret="test", allowed_group_ids=",".join(groups))
        requests = []
        def respond(request):
            batch = json.loads(request.content)["groupIds"]
            requests.append(batch)
            return httpx.Response(200, json={"value": [groups[-1]] if groups[-1] in batch else []})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        tokens = Mock(acquire_token_for_client=Mock(return_value={"access_token": "fixture"}))
        auth = GroupAuthorizer(cfg, token_client=tokens, http=client)
        try:
            self.assertTrue(await auth.allowed(USER))
            self.assertTrue(await auth.allowed(USER))
            self.assertEqual([len(batch) for batch in requests], [20, 2, 20, 2])
        finally:
            await auth.close()

    async def test_denied_and_unavailable_are_distinct(self):
        for status, payload in ((200, {"value": []}), (403, {}), (503, {}), (200, {})):
            auth = GroupAuthorizer(config(), token_client=Mock(acquire_token_for_client=Mock(return_value={"access_token": "fixture"})),
                http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload, headers={"Retry-After": "60"}))))
            try:
                if status == 200 and "value" in payload:
                    self.assertFalse(await auth.allowed(USER))
                else:
                    with self.assertRaises(AccessUnavailable):
                        await auth.allowed(USER)
            finally:
                await auth.close()


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.store = RequestStore(Path(self.tmp.name) / "inbox.db")
        await self.store.start()
        self.sender = Sender(TENANT, USER, "conv", "one", SERVICE)

    async def asyncTearDown(self):
        await self.store.close()
        self.tmp.cleanup()

    async def test_duplicate_is_one_job_and_second_query_is_blocked(self):
        ids = await asyncio.gather(*[self.store.enqueue(self.sender, "all users", None) for _ in range(5)])
        self.assertEqual(len(set(ids)), 1)
        with self.assertRaises(InboxFull):
            await self.store.enqueue(Sender(TENANT, USER, "conv", "two", SERVICE), "other question", None)
        await self.store.enqueue(Sender(TENANT, USER, "conv", "cancel", SERVICE), "cancel", None)
        self.assertIsNotNone(await self.store.claim(command=True))
        self.assertEqual((await self.store.claim(command=False))["id"], ids[0])
        self.assertIsNone(await self.store.claim(command=False))

    async def test_restart_never_replays_running_job(self):
        await self.store.enqueue(self.sender, "all users", None)
        running = await self.store.claim(command=False)
        await self.store.close()
        await self.store.start()
        self.assertIsNone(await self.store.claim(command=False))
        row = await (await self.store.db.execute("SELECT status FROM teams_requests WHERE id=?", (running["id"],))).fetchone()
        self.assertEqual(row["status"], "interrupted")

    async def test_single_process_lease(self):
        another = RequestStore(self.store.path)
        with self.assertRaises(RuntimeError):
            await another.start()

    async def test_cancel_only_owners_queued_request(self):
        await self.store.enqueue(self.sender, "all users", None)
        self.assertEqual(await self.store.cancel_queued(TENANT, CLIENT), 0)
        self.assertEqual(await self.store.cancel_queued(TENANT, USER), 1)
        self.assertIsNone(await self.store.claim(command=False))


class SDKAndWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.auth = SimpleNamespace(allowed=AsyncMock(return_value=True), close=AsyncMock())
        self.runner = AsyncMock(return_value={"display_type": "table", "results": [{"email": "user@example.test"}], "outcome": "completed"})
        self.bot = TeamsBot(config(), Path(self.tmp.name), authorizer=self.auth, runner=self.runner)
        # Initialize the real SDK route/auth pipeline but do not start background workers.
        await self.bot.store.start()
        await self.bot.sdk.initialize()
        self.delete_progress = AsyncMock()
        cleanup_patch = patch.object(self.bot.sdk.api.conversations, "delete_activity", self.delete_progress)
        cleanup_patch.start()
        self.addCleanup(cleanup_patch.stop)
        self.bot.sdk.server.on_request = self.bot.receive
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.bot.http_app), base_url="http://fixture")
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def asyncTearDown(self):
        await self.http.aclose()
        await self.bot.close()
        self.tmp.cleanup()

    def token(self, **overrides):
        return jwt.encode({"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 3600,
                           "iat": int(time.time()), "serviceurl": SERVICE, **overrides}, self.key, algorithm="RS256")

    async def post_signed(self, *, token=None, body=None):
        # Only key discovery is mocked. The SDK still verifies signature/audience/expiry.
        with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=SimpleNamespace(key=self.key.public_key())):
            return await self.http.post("/messages", json=body or activity(), headers={"Authorization": "Bearer " + (token or self.token())})

    async def test_unsigned_or_invalid_tokens_never_enqueue(self):
        self.assertEqual((await self.http.post("/messages", json=activity())).status_code, 401)
        for token in (self.token(aud=TENANT), self.token(exp=time.time() - 1000), self.token(serviceurl="https://evil.test/"),
                      jwt.encode({"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 3600}, "wrong-key" * 5, algorithm="HS256")):
            self.assertEqual((await self.post_signed(token=token)).status_code, 401)
        self.assertIsNone(await self.bot.store.claim(command=False))
        self.runner.assert_not_awaited()

    async def test_valid_token_acknowledges_without_model_or_graph_and_deduplicates(self):
        self.assertEqual((await self.post_signed()).status_code, 200)
        self.assertEqual((await self.post_signed()).status_code, 200)
        self.auth.allowed.assert_not_awaited()
        self.runner.assert_not_awaited()
        self.assertIsNotNone(await self.bot.store.claim(command=False))
        self.assertIsNone(await self.bot.store.claim(command=False))

    async def test_authenticated_wrong_tenant_and_shared_chat_rejected(self):
        wrong = activity()
        wrong["channelData"]["tenant"]["id"] = CLIENT
        self.assertEqual((await self.post_signed(body=wrong)).status_code, 403)
        wrong = activity()
        wrong["conversation"]["conversationType"] = "channel"
        self.assertEqual((await self.post_signed(body=wrong)).status_code, 403)

    async def test_teams_html_companion_and_unicode_use_only_message_text(self):
        body = activity()
        body["text"] = "\ufeff  List Jos\u00e9\u2019s users & groups \U0001f419\r\nall\u00a0statuses\x00\u202e  "
        body["attachments"] = [{"contentType": "text/html", "content": "<p>Different content</p>"}]
        with self.assertLogs("src.integrations.teams.teams_app", level="INFO") as captured:
            self.assertEqual((await self.post_signed(body=body)).status_code, 200)
        queued = await self.bot.store.claim(command=False)
        self.assertEqual(queued["query"], "List Jos\u00e9\u2019s users & groups \U0001f419\nall statuses")
        self.assertIn("html_attachments=1", " ".join(captured.output))
        self.assertNotIn("Different content", " ".join(captured.output))
        self.assertNotIn(body["text"].strip(), " ".join(captured.output))
        self.auth.allowed.assert_not_awaited()
        self.runner.assert_not_awaited()

    async def test_rejection_reasons_keep_payloads_private(self):
        cases = [
            ({"attachments": [{"contentType": "text/html", "content": "private-html"},
                              {"contentType": "application/vnd.microsoft.teams.file.download.info",
                               "content": {"downloadUrl": "https://private.test/secret"}}]}, "unsupported_attachment"),
            ({"value": {"secret": "private-action"}}, "unsupported_card_action"),
            ({"text": " ", "attachments": [{"contentType": "text/html", "content": "private-html"}]}, "empty_text"),
            ({"text": "x" * 8001}, "text_too_long"),
            ({"text": "\ufeff\u202e\x00"}, "empty_text"),
            ({"type": "invoke", "name": "task/fetch"}, "unsupported_invoke"),
        ]
        for update, reason in cases:
            with self.subTest(reason=reason):
                body = {**activity(), **update}
                with self.assertLogs("src.integrations.teams.teams_app", level="WARNING") as captured:
                    self.assertEqual((await self.post_signed(body=body)).status_code, 400)
                logs = " ".join(captured.output)
                self.assertIn("reason=" + reason, logs)
                for private in ("private-html", "private-action", "private.test", "List all users", "xxx"):
                    self.assertNotIn(private, logs)
        self.assertIsNone(await self.bot.store.claim(command=False))
        self.runner.assert_not_awaited()

    async def test_denied_membership_does_not_run_query(self):
        self.auth.allowed.return_value = False
        self.bot.send = AsyncMock()
        await self.bot.process(job())
        self.runner.assert_not_awaited()
        self.assertIn("don't have access", self.bot.send.call_args.args[1]["content"])

    async def test_revoked_membership_withholds_final_data(self):
        self.auth.allowed.side_effect = [True, False]
        self.bot.send = AsyncMock(return_value=SimpleNamespace(id="progress"))
        await self.bot.process(job())
        self.runner.assert_awaited_once()
        self.assertEqual(self.bot.send.await_count, 1)
        self.assertEqual(self.bot.send.call_args.args[1]["outcome"], "working")

    async def test_completed_result_sends_new_message_then_removes_progress(self):
        self.bot.send = AsyncMock(return_value=SimpleNamespace(id="progress"))
        await self.bot.process(job())
        self.assertEqual(self.auth.allowed.await_count, 2)
        self.assertNotIn("activity_id", self.bot.send.call_args.kwargs)
        self.delete_progress.assert_awaited_once_with(job()["conversation"], "progress", service_url=SERVICE)

    async def test_final_delivery_cleans_up_only_after_success_and_never_resends(self):
        for outcome in ("completed", "fail", "cancelled", "clarify"):
            with self.subTest(outcome=outcome):
                order = []
                async def send(*args, **kwargs):
                    self.assertNotIn("activity_id", kwargs)
                    order.append("send")
                async def delete(*args, **kwargs):
                    order.append("delete")
                    raise RuntimeError("fixture cleanup failure")
                self.bot.send = AsyncMock(side_effect=send)
                self.delete_progress.side_effect = delete
                with self.assertLogs("src.integrations.teams.teams_app", level="WARNING"):
                    await self.bot.send_final(job(progress_id="progress"), {"outcome": outcome})
                self.assertEqual(order, ["send", "delete"])
                self.bot.send.assert_awaited_once()
        self.delete_progress.reset_mock(side_effect=True)
        self.bot.send = AsyncMock(side_effect=RuntimeError("fixture delivery failure"))
        pending = job(progress_id="progress")
        with self.assertRaises(RuntimeError):
            await self.bot.send_final(pending, {"outcome": "completed"})
        self.delete_progress.assert_not_awaited()
        self.assertEqual(pending["progress_id"], "progress")

    async def test_error_and_cancellation_send_a_new_final_card(self):
        self.bot.send = AsyncMock()
        for outcome in ("fail", "cancelled"):
            await self.bot.report_failure(job(progress_id="progress"), "Stopped", outcome=outcome)
            self.assertNotIn("activity_id", self.bot.send.call_args.kwargs)
        self.assertEqual(self.delete_progress.await_count, 2)

    async def test_real_sdk_sends_one_card_and_updates_its_returned_id(self):
        requests = []
        async def connector(http, method, url, **kwargs):
            requests.append((method, url, kwargs["json"]))
            return httpx.Response(200, json={"id": "progress123"}, request=httpx.Request(method, url))
        with patch.object(self.bot.sdk.token_provider, "get_app_token", AsyncMock(return_value="fixture-token")), \
             patch.object(httpx.AsyncClient, "request", connector):
            sent = await self.bot.send(job(), {"content": "Working", "outcome": "working"})
            await self.bot.send(job(), {"content": "Unable to complete", "outcome": "fail"}, activity_id=sent.id)
        self.assertEqual([request[0] for request in requests], ["POST", "PUT"])
        self.assertTrue(requests[1][1].endswith("/activities/progress123"))
        for _, _, payload in requests:
            self.assertNotIn("text", payload)
            self.assertEqual(len(payload["attachments"]), 1)
            self.assertEqual(payload["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")

    async def test_help_and_cancel_do_not_call_model(self):
        self.bot.send = AsyncMock()
        await self.bot.process(job(query="help", command=1))
        await self.bot.process(job(query="cancel", command=1))
        self.runner.assert_not_awaited()

    async def test_signed_card_actions_and_file_consent_are_queued_without_model(self):
        reference = "66666666666666666666666666666666:1"
        body = activity(text="", value={"tako_action": "download", "reference": reference})
        self.assertEqual((await self.post_signed(body=body)).status_code, 200)
        queued = await self.bot.store.claim(command=True)
        self.assertEqual(queued["action"], "download")
        await self.bot.store.finish(queued["id"], "completed")
        body = activity(id="consent-event", type="invoke", name="fileConsent/invoke", text="", value={
            "type": "fileUpload", "action": "accept", "context": {"download_id": "77777777-7777-7777-7777-777777777777"},
            "uploadInfo": {"uploadUrl": "https://fixture.up.1drv.com/upload?token=private",
                           "contentUrl": "https://fixture.sharepoint.com/file.csv", "uniqueId": "file", "name": "file.csv", "fileType": "csv"},
        })
        self.assertEqual((await self.post_signed(body=body)).status_code, 200)
        queued = await self.bot.store.claim(command=True)
        self.assertEqual(queued["action"], "file_accept")
        self.runner.assert_not_awaited()
        self.auth.allowed.assert_not_awaited()

    async def test_new_query_resets_session_without_calling_model(self):
        original = await self.bot.store.bind_session(job(), 24)
        self.bot.send = AsyncMock()
        from uuid import uuid4
        reset = job(id=str(uuid4()), query="New Query", action="new_query")
        await self.bot.process(reset)
        self.assertNotEqual(reset["session_id"], original)
        self.assertEqual(await self.bot.store.bind_session(job(id=str(uuid4())), 24), reset["session_id"])
        self.runner.assert_not_awaited()

    async def test_download_consent_upload_and_replay_never_call_model(self):
        from src.integrations.teams import files
        from uuid import uuid4
        path = Path(self.tmp.name) / "export.csv"
        path.write_text("email\nfixture@example.test\n", encoding="utf-8")
        reference = f"{uuid4().hex}:1"
        self.bot.send_attachment = AsyncMock()
        self.bot.send = AsyncMock()
        with patch.object(files, "export_path", AsyncMock(return_value=path)), \
             patch.object(files, "upload_csv", AsyncMock()) as upload:
            await self.bot.process(job(action="download", reference=reference, query="Download CSV", command=1))
            attachment = self.bot.send_attachment.call_args.args[1]
            token = attachment["content"]["acceptContext"]["download_id"]
            info = {"uploadUrl": "https://fixture.up.1drv.com/upload", "contentUrl": "https://fixture.sharepoint.com/file.csv", "uniqueId": "file"}
            upload.return_value = info
            consent = job(id=str(uuid4()), action="file_accept", reference=token, payload=json.dumps(info), command=1)
            await self.bot.process(consent)
            upload.assert_awaited_once_with(path, info)
            self.assertEqual(self.bot.send_attachment.call_args.args[1]["contentType"], "application/vnd.microsoft.teams.card.file.info")
            await self.bot.process({**consent, "id": str(uuid4())})
            self.assertEqual(upload.await_count, 1)
            self.assertIn("expired", self.bot.send.call_args.args[1]["content"])
        self.runner.assert_not_awaited()

    async def test_real_worker_processes_job_once(self):
        self.bot.send = AsyncMock(return_value=SimpleNamespace(id="progress"))
        await self.bot.store.enqueue(Sender(TENANT, USER, "conv", "a", SERVICE), "List users", None)
        worker = asyncio.create_task(self.bot.worker(command=False))
        self.bot.tasks.append(worker)
        for _ in range(100):
            rows = await (await self.bot.store.db.execute("SELECT status FROM teams_requests")).fetchall()
            if rows and rows[0]["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(rows[0]["status"], "completed")
        self.runner.assert_awaited_once()

    async def test_typing_indicator_sends_native_activity_and_stops_on_failure(self):
        self.bot.sdk.send = AsyncMock(side_effect=httpx.HTTPStatusError(
            "throttled", request=httpx.Request("POST", SERVICE), response=httpx.Response(429)))
        with self.assertLogs("src.integrations.teams.teams_app", level="WARNING"):
            await self.bot.typing_indicator(job())
        self.bot.sdk.send.assert_awaited_once()
        activity = self.bot.sdk.send.call_args.args[1]
        self.assertEqual(activity.type, "typing")
        self.assertEqual(self.bot.sdk.send.call_args.kwargs["service_url"], SERVICE)
        self.runner.assert_not_awaited()

    async def test_query_stops_typing_on_success_failure_and_cancel(self):
        for outcome in ("success", "failure", "cancel"):
            started, stopped, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def indicator(_):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            async def runner(_):
                await release.wait()
                if outcome == "failure":
                    raise ValueError("fixture")
                return {"content": "Complete"}
            self.bot.typing_indicator = indicator
            self.bot.runner = runner
            async def send(_, response):
                if response.get("outcome") != "working":
                    self.assertTrue(stopped.is_set(), "Typing must stop before the final message")
                return SimpleNamespace(id="progress")
            self.bot.send = AsyncMock(side_effect=send)
            task = asyncio.create_task(self.bot.process(job()))
            try:
                await asyncio.wait_for(started.wait(), 1)
                if outcome == "cancel":
                    task.cancel()
                else:
                    release.set()
                if outcome == "success":
                    await task
                else:
                    with self.assertRaises(asyncio.CancelledError if outcome == "cancel" else ValueError):
                        await task
                self.assertTrue(stopped.is_set())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
