import asyncio
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

from multidict import CIMultiDict

# Импорт не читает рабочий .env и не создаёт /app.
with patch("dotenv.load_dotenv"), patch("os.makedirs"):
    import smule_bot


def response(status=200, payload=None, *, body=None, headers=None):
    resp = MagicMock()
    resp.status = status
    resp.headers = CIMultiDict(headers or {"Content-Type": "application/json"})
    resp.text = AsyncMock(return_value=body if body is not None else json.dumps(payload))
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def session_with(*responses):
    session = MagicMock()
    session.get.side_effect = responses
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class SmuleFailuresTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(data_dir.cleanup)
        self.enterContext(patch.object(smule_bot, "DATA_DIR", data_dir.name))
        self.enterContext(patch.dict("os.environ", {
            "SMULE_COOKIE": "", "SMULE_REQUEST_DELAY": "0", "SMULE_BLOCK_COOLDOWN": "900",
        }))
        self.enterContext(patch.object(smule_bot, "Bot"))
        self.bot = smule_bot.SmuleFollowersBot("test-token", "test-chat", ["first", "second"])
        self.bot._send_text = AsyncMock(return_value=True)
        self.bot._send_batch_messages = AsyncMock()
        self.sleep = self.enterContext(patch.object(smule_bot.asyncio, "sleep", new_callable=AsyncMock))

    async def test_cloudflare_html_is_not_an_empty_page(self):
        session = session_with(response(403, body="<!DOCTYPE html><title>Just a moment...</title>",
                                        headers={"Content-Type": "text/html", "Server": "cloudflare"}))
        with self.assertRaisesRegex(smule_bot.SmuleAccessBlocked, "HTTP 403.*Cloudflare"):
            await self.bot._check_account_with_retry(session, "first")
        self.assertEqual(session.get.call_count, 1)
        self.sleep.assert_not_awaited()
        self.bot._send_batch_messages.assert_not_awaited()

    async def test_challenge_header_is_detected_even_with_http_200(self):
        session = session_with(response(body="<html>Challenge</html>", headers={"CF-Mitigated": "challenge"}))
        with self.assertRaisesRegex(smule_bot.SmuleAccessBlocked, "HTTP 200"):
            await self.bot._get_followers_page(session, "first")

    async def test_429_honors_retry_after(self):
        session = session_with(response(429, headers={"Retry-After": "7200"}))
        with self.assertRaises(smule_bot.SmuleAccessBlocked) as caught:
            await self.bot._get_followers_page(session, "first")
        self.assertEqual(caught.exception.retry_after, 7200)

    def test_retry_after_dates_and_invalid_values(self):
        parse = self.bot._retry_after_seconds
        future = format_datetime(datetime.now(timezone.utc) + timedelta(hours=2), usegmt=True)
        self.assertGreater(parse(future), 7190)
        self.assertLessEqual(parse(future), 7200)
        for value in ("", "invalid", "-10", "nan", "Thu, 01 Jan 1970 00:00:00 GMT"):
            with self.subTest(value=value):
                self.assertEqual(parse(value), 0)

    async def test_invalid_payload_never_becomes_a_follower_snapshot(self):
        for payload in (None, [], {}, {"list": None}, {"list": {}}, {"list": [None]}, {"list": [{}]}):
            with self.subTest(payload=payload):
                with self.assertRaises(smule_bot.SmuleAPIError):
                    await self.bot._get_followers_page(session_with(response(payload=payload)), "first")
        with self.assertRaisesRegex(smule_bot.SmuleAPIError, "JSON"):
            await self.bot._get_followers_page(session_with(response(body="not json")), "first")

    async def test_timeout_is_retried_on_the_same_page(self):
        session = session_with(asyncio.TimeoutError(), response(payload={"list": []}))
        self.assertEqual(await self.bot._get_all_followers(session, "first"), [])
        self.assertEqual([c.kwargs["params"]["offset"] for c in session.get.call_args_list], [0, 0])
        self.sleep.assert_awaited_once_with(2.0)

    async def test_server_error_recovers_without_restarting_pagination(self):
        batch = [{"account_id": i} for i in range(1, 21)]
        last = {"account_id": 21}
        session = session_with(response(payload={"list": batch}), response(503), response(payload={"list": [last]}))
        self.assertEqual(await self.bot._get_all_followers(session, "first"), batch + [last])
        self.assertEqual([c.kwargs["params"]["offset"] for c in session.get.call_args_list], [0, 20, 20])

    async def test_retry_exhaustion_does_not_multiply_account_retries(self):
        session = session_with(*(response(502) for _ in range(3)))
        with self.assertRaisesRegex(smule_bot.SmuleAPIError, "HTTP 502"):
            await self.bot._check_account_with_retry(session, "first")
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(self.sleep.await_args_list, [call(2.0), call(4.0)])

    async def test_permanent_http_error_is_not_retried(self):
        session = session_with(response(404))
        with self.assertRaisesRegex(smule_bot.SmuleAPIError, "HTTP 404"):
            await self.bot._check_account_with_retry(session, "first")
        self.assertEqual(session.get.call_count, 1)

    async def test_partial_load_preserves_followers_and_metadata_on_disk(self):
        self.bot.known_followers["first"] = {"old"}
        self.bot.followers_meta["first"] = {"old": {"account_id": "old", "handle": "old"}}
        self.bot._save_followers_set("first")
        self.bot._save_followers_meta("first")
        files = [Path(self.bot._followers_file("first")), Path(self.bot._followers_meta_file("first"))]
        before = [p.read_bytes() for p in files]
        batch = [{"account_id": i} for i in range(1, 21)]
        session = session_with(response(payload={"list": batch}), response(403))
        with patch.object(self.bot, "_build_session", return_value=session):
            await self.bot.check_new_followers()
        self.assertEqual([p.read_bytes() for p in files], before)
        self.assertEqual(self.bot.known_followers["first"], {"old"})
        self.assertEqual(set(self.bot.followers_meta["first"]), {"old"})
        self.bot._send_batch_messages.assert_not_awaited()
        self.bot._send_text.assert_awaited_once()
        self.assertEqual([c.kwargs["params"]["accountId"] for c in session.get.call_args_list], ["first", "first"])

    async def test_cooldown_skips_network_and_notifications_then_recovers(self):
        blocked = session_with(response(429, headers={"Retry-After": "7200"}))
        with patch.object(smule_bot.time, "monotonic", return_value=100), \
                patch.object(self.bot, "_build_session", return_value=blocked) as build:
            await self.bot.check_new_followers()
            await self.bot.check_new_followers()
            self.assertEqual(self.bot._smule_blocked_until, 7300)
            self.assertEqual(build.call_count, 1)
            self.bot._send_text.assert_awaited_once()
        healthy = session_with(response(payload={"list": []}), response(payload={"list": []}))
        with patch.object(smule_bot.time, "monotonic", return_value=7301), \
                patch.object(self.bot, "_build_session", return_value=healthy):
            await self.bot.check_new_followers()
        self.assertEqual(healthy.get.call_count, 2)
        self.assertEqual(self.bot._smule_block_count, 0)
        self.assertEqual(self.bot._smule_blocked_until, 0)

    async def test_repeated_blocks_increase_the_pause_with_a_cap(self):
        now = 100
        for delay in (900, 1800, 3600, 3600):
            with patch.object(smule_bot.time, "monotonic", return_value=now), \
                    patch.object(self.bot, "_build_session", return_value=session_with(response(403))):
                await self.bot.check_new_followers()
            self.assertEqual(self.bot._smule_blocked_until, now + delay)
            now += delay + 1

    async def test_request_pacing_is_shared_between_accounts(self):
        self.bot.smule_request_delay = 3
        session = session_with(response(payload={"list": []}), response(payload={"list": []}))
        with patch.object(smule_bot.time, "monotonic", side_effect=[100, 101, 103]):
            await self.bot._get_followers_page(session, "first")
            await self.bot._get_followers_page(session, "second")
        self.sleep.assert_awaited_once_with(2)

    async def test_failed_account_is_not_counted_as_successful(self):
        session = session_with(response(404), response(payload={"list": [{"account_id": 1}]}))
        with patch.object(self.bot, "_build_session", return_value=session):
            await self.bot.check_new_followers()
        summary = self.bot._send_text.await_args.args[0]
        self.assertIn("Проверено: 1/2", summary)
        self.assertIn("Новых: 1", summary)

    async def test_successful_load_still_saves_snapshot_and_sends_changes(self):
        self.bot.known_followers["first"] = {"old"}
        session = session_with(response(payload={"list": [{"account_id": "new", "handle": "new"}]}))
        self.assertEqual(await self.bot._check_account(session, "first"), (1, 1))
        self.assertEqual(json.loads(Path(self.bot._followers_file("first")).read_text()), ["new"])
        self.assertEqual(self.bot._send_batch_messages.await_count, 2)

    async def test_monitoring_loop_respects_cooldown(self):
        self.bot._smule_blocked_until = 1000
        with patch.object(self.bot, "check_new_followers", new_callable=AsyncMock), \
                patch.object(smule_bot.time, "monotonic", return_value=100):
            self.sleep.side_effect = asyncio.CancelledError
            with self.assertRaises(asyncio.CancelledError):
                await self.bot.run_continuous(check_interval=300)
        self.sleep.assert_awaited_once_with(900)

    def test_http_request_logs_do_not_expose_telegram_token(self):
        self.assertFalse(logging.getLogger("httpx").isEnabledFor(logging.INFO))
        self.assertFalse(logging.getLogger("httpcore").isEnabledFor(logging.DEBUG))


if __name__ == "__main__":
    unittest.main()
