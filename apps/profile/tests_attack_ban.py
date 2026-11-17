"""Who AttackBanMiddleware bans, for how long, and when it only logs.

The ban list used to read the leftmost X-Forwarded-For entry, ban private
infrastructure addresses, and hold every ban for 24 hours. A single request with
"><script> in its query string locked this machine out of its own dev server for a
day. utils/ip_rate_tracker.py now counts the header from the right (our proxies
append the rightmost entries), refuses to ban non-public addresses, and escalates
instead of banning a day outright.
"""

import json as std_json
from unittest import mock

from django.conf import settings as django_settings
from django.test import RequestFactory, TestCase, override_settings

from apps.profile.middleware import AttackBanMiddleware, UserAgentBanMiddleware
from utils.ip_rate_tracker import AttackDetector, _get_client_ip, is_bannable_ip

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
PAYLOAD = "<script>alert(1)</script>"


class FakeRedis:
    """Enough of the redis client for AttackDetector, without a server."""

    def __init__(self):
        self.store = {}
        self.ttl = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        if ex is not None:
            self.ttl[key] = ex

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def hset(self, key, mapping=None):
        self.store.setdefault(key, {})
        self.store[key].update(mapping or {})

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return record

    def execute(self):
        for name, args, kwargs in self.calls:
            getattr(self.client, name)(*args, **kwargs)
        self.calls = []


class ClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def ip(self, forwarded=None, remote="10.0.0.1"):
        extra = {"REMOTE_ADDR": remote}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return _get_client_ip(self.factory.get("/", **extra))

    def test_client_is_the_entry_before_our_proxy_append(self):
        # openresty appends the Cloudflare edge address, so the client is one left.
        self.assertEqual(self.ip("203.0.113.7, 198.51.100.1"), "203.0.113.7")

    def test_prepended_entries_do_not_change_the_answer(self):
        # A client can prepend anything; the entries to the right are ours.
        self.assertEqual(
            self.ip("1.1.1.1, 2.2.2.2, 203.0.113.7, 198.51.100.1"), "203.0.113.7"
        )

    def test_single_entry_falls_back_to_it(self):
        self.assertEqual(self.ip("203.0.113.7"), "203.0.113.7")

    def test_missing_header_uses_remote_addr(self):
        self.assertEqual(self.ip(), "10.0.0.1")

    @override_settings(ATTACK_BAN_PROXY_HOPS=0)
    def test_no_proxy_hops_ignores_the_header(self):
        self.assertEqual(self.ip("203.0.113.7, 198.51.100.1"), "10.0.0.1")

    @override_settings(ATTACK_BAN_PROXY_HOPS=2)
    def test_two_hops_read_one_entry_further_left(self):
        self.assertEqual(
            self.ip("203.0.113.7, 198.51.100.1, 192.0.2.9"), "203.0.113.7"
        )

    def test_garbage_entry_falls_back_to_remote_addr(self):
        self.assertEqual(self.ip("not-an-ip, 198.51.100.1"), "10.0.0.1")


class BannableIpTests(TestCase):
    def test_public_addresses_are_bannable(self):
        for ip in ("8.8.8.8", "2001:4860::8888"):
            self.assertTrue(is_bannable_ip(ip), ip)

    def test_shared_infrastructure_is_not_bannable(self):
        # 172.18.0.1 is the docker gateway that once locked the dev server out.
        for ip in (
            "172.18.0.1",
            "127.0.0.1",
            "10.0.0.5",
            "100.64.1.1",
            "169.254.1.1",
            "::1",
            "fc00::1",
        ):
            self.assertFalse(is_bannable_ip(ip), ip)

    def test_junk_is_not_bannable(self):
        self.assertFalse(is_bannable_ip("unknown"))
        self.assertFalse(is_bannable_ip(""))


class BanLadderTests(TestCase):
    def setUp(self):
        self.detector = AttackDetector()
        self.fake = FakeRedis()
        self.detector._redis = self.fake
        self.request = RequestFactory().get("/reader/feeds?q=x", HTTP_USER_AGENT=UA)

    def test_bans_escalate_and_then_hold(self):
        durations = [
            self.detector.ban_ip("8.8.8.8", "xss", PAYLOAD, self.request) for _ in range(4)
        ]
        self.assertEqual(durations, [600, 3600, 86400, 86400])
        self.assertEqual(self.fake.ttl["atk:ban:8.8.8.8"], 86400)
        self.assertEqual(
            self.fake.ttl["atk:strikes:8.8.8.8"], AttackDetector.STRIKE_TTL_SECONDS
        )

    def test_log_records_the_rung(self):
        self.detector.ban_ip("8.8.8.8", "xss", PAYLOAD, self.request)
        log = self.fake.store["atk:log:8.8.8.8"]
        self.assertEqual(log["strikes"], "1")
        self.assertEqual(log["ban_seconds"], "600")
        self.assertEqual(log["attack_type"], "xss")


class MiddlewareTests(TestCase):
    def setUp(self):
        self.detector = AttackDetector()
        self.fake = FakeRedis()
        self.detector._redis = self.fake
        patcher = mock.patch.object(
            AttackBanMiddleware,
            "detector",
            new_callable=mock.PropertyMock,
            return_value=self.detector,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, path="/account/login/", data=None, **extra):
        extra.setdefault("HTTP_USER_AGENT", UA)
        return self.client.get(path, data or {}, **extra)

    @override_settings(ATTACK_BAN_DRY_RUN=False)
    def test_private_client_is_never_banned(self):
        response = self.get(data={"next": PAYLOAD}, REMOTE_ADDR="172.18.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("atk:ban:172.18.0.1", self.fake.store)

    @override_settings(ATTACK_BAN_DRY_RUN=False)
    def test_public_client_is_banned(self):
        response = self.get(data={"next": PAYLOAD}, REMOTE_ADDR="8.8.8.8")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.store.get("atk:ban:8.8.8.8"), "1")

    @override_settings(ATTACK_BAN_DRY_RUN=False)
    def test_banned_client_is_rejected_without_inspection(self):
        self.fake.store["atk:ban:8.8.8.8"] = "1"
        response = self.get(REMOTE_ADDR="8.8.8.8")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(std_json.loads(response.content)["error"], "Forbidden")

    @override_settings(ATTACK_BAN_DRY_RUN=True)
    def test_dry_run_logs_without_banning(self):
        response = self.get(data={"next": PAYLOAD}, REMOTE_ADDR="8.8.8.8")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("atk:ban:8.8.8.8", self.fake.store)
        self.assertNotIn("atk:strikes:8.8.8.8", self.fake.store)

    def test_dry_run_is_the_local_default(self):
        # settings.ATTACK_BAN_DRY_RUN defaults to DEBUG, so this checkout cannot
        # ban itself while someone is testing payload handling.
        self.assertTrue(django_settings.ATTACK_BAN_DRY_RUN)


class UserAgentBanPathTests(TestCase):
    def test_account_paths_are_skipped(self):
        response = self.client.get("/account/login/", HTTP_USER_AGENT="missing")
        self.assertEqual(response.status_code, 200)

    def test_paths_that_only_contain_account_are_not_skipped(self):
        # The old substring test ("account" in path) skipped this path too.
        response = self.client.get("/reader/foo/account/bar", HTTP_USER_AGENT="missing")
        self.assertEqual(response.status_code, 403)
        self.assertIn("User agent banned", std_json.loads(response.content)["error"])


class SkipPathPrefixTests(TestCase):
    def test_prefixes_cover_the_routes_that_need_them(self):
        prefixes = UserAgentBanMiddleware.SKIP_PATH_PREFIXES
        for path in ("/account/login/", "/profile/set_preference", "/push/", "/haproxy", "/dbcheck"):
            self.assertTrue(path.startswith(prefixes), path)
