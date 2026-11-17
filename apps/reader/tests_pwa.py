"""The installable shell: manifest, service worker, and offline page.

These endpoints are public by design. The tests pin the contract the browser
depends on: a manifest with installable icons and a root scope, a worker served
from the origin root with a no-store policy, and an offline page that carries no
account data.
"""

import json
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.url_map import build_url_map

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class PwaTests(TestCase):
    def client_kwargs(self):
        # Production redirects every plain-HTTP request to HTTPS and the attack
        # middleware rejects requests without a browser User-Agent. Supply both
        # so these tests exercise the PWA views rather than the front door.
        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        host = allowed_hosts[0] if allowed_hosts and allowed_hosts[0] != "*" else "testserver"
        return {"secure": True, "HTTP_HOST": host, "HTTP_USER_AGENT": UA}

    def test_manifest_is_installable_and_scoped_to_the_origin(self):
        response = self.client.get("/manifest.webmanifest", **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        self.assertIn("max-age=300", response["Cache-Control"])

        manifest = json.loads(response.content)
        self.assertEqual(manifest["id"], "/")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["theme_color"], "#1875F3")

        icons = {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]}
        self.assertIn(("192x192", "any"), icons)
        self.assertIn(("512x512", "any"), icons)
        self.assertIn(("512x512", "maskable"), icons)
        self.assertTrue(all(icon["src"].startswith(settings.MEDIA_URL) for icon in manifest["icons"]))

        shortcuts = {shortcut["name"]: shortcut["url"] for shortcut in manifest["shortcuts"]}
        self.assertEqual(shortcuts["All Stories"], "/reader/")
        self.assertEqual(shortcuts["Saved Stories"], "/saved/")

    def test_service_worker_is_served_from_the_root_with_no_store(self):
        response = self.client.get("/service-worker.js", **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/javascript", response["Content-Type"])
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("no-store", response["Cache-Control"])

        body = response.content.decode()
        self.assertIn("newsblur-shell-", body)
        self.assertIn("cache.addAll", body)
        self.assertIn("self.skipWaiting()", body)
        self.assertIn("self.clients.claim()", body)
        # The worker must never cache navigation responses; the offline shell is
        # the only HTML it stores.
        self.assertIn('request.mode === "navigate"', body)
        self.assertIn('"/offline"', body)

    def test_navigation_only_falls_back_when_the_network_is_gone(self):
        response = self.client.get("/service-worker.js", **self.client_kwargs())
        body = response.content.decode()
        navigate = body.split('if (request.mode === "navigate") {', 1)[1].split(
            "if (!is_static_request", 1
        )[0]
        # A 404 or 500 is an answer from the server, not an offline state. Only a
        # rejected fetch may be replaced with the offline shell.
        self.assertIn("fetch(request).catch", navigate)
        self.assertNotIn("response.ok", navigate)

    def test_offline_page_is_public_and_has_no_account_data(self):
        user = User.objects.create_user(
            "pwa-offline-user", email="pwa-offline@example.com", password="not-used"
        )
        self.client.force_login(user)

        response = self.client.get("/offline/", **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=86400", response["Cache-Control"])
        body = response.content.decode()
        self.assertIn('class="NB-offline"', body)
        self.assertRegex(body, r"pwa-offline\.[0-9a-f]{12}\.css")
        self.assertNotIn(user.username, body)
        self.assertNotIn(user.email, body)

        worker = self.client.get("/service-worker.js", **self.client_kwargs()).content.decode()
        version = re.search(r"pwa-offline\.[0-9a-f]{12}\.css\?v=([^\"&]+)", worker).group(1)
        self.assertIn(f"?v={version}", body)

    def test_base_page_links_the_manifest_and_theme(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('rel="manifest"', body)
        self.assertIn("/manifest.webmanifest", body)
        self.assertIn('name="theme-color"', body)
        self.assertIn("img/pwa/apple-touch-icon.png", body)

    def test_worker_path_is_in_the_generated_url_map(self):
        self.assertEqual(build_url_map()["pwa-service-worker"], "/service-worker.js")
