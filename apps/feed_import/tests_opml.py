"""OPML uploads are decoded to text before they reach the database (feed_import.views.opml_upload)."""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.feed_import.models import UploadedOPML

# The reader rejects requests without a user agent, so the upload carries a real one.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

OPML = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline text="Fresh">
      <outline type="rss" text="Example" xmlUrl="http://example.com/feed" />
    </outline>
  </body>
</opml>
"""


class Test_OpmlUpload(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("opmler", "opmler@example.com", "opmler-password")
        self.client.force_login(self.user)
        self.client.defaults["HTTP_USER_AGENT"] = UA

    @patch("apps.feed_import.views.ProcessOPML.delay")
    def test_stores_the_upload_as_text(self, delay):
        response = self.client.post(
            "/import/opml_upload", {"file": SimpleUploadedFile("subscriptions.opml", OPML)}
        )
        body = json.loads(response.content)

        self.assertEqual(body["code"], 2, body)
        uploaded = UploadedOPML.objects.get(user_id=self.user.pk)
        self.assertIsInstance(uploaded.opml_file, str)
        self.assertTrue(uploaded.opml_file.startswith("<?xml"))
        delay.assert_called_once()

    @patch("apps.feed_import.views.ProcessOPML.delay")
    def test_rejects_a_file_that_is_not_utf8(self, delay):
        response = self.client.post(
            "/import/opml_upload", {"file": SimpleUploadedFile("subscriptions.opml", b"\xff\xfe\x00zip")}
        )
        body = json.loads(response.content)

        self.assertEqual(body["code"], -1, body)
        self.assertIn("Unicode decode error", body["message"])
        self.assertFalse(UploadedOPML.objects.filter(user_id=self.user.pk).exists())
        delay.assert_not_called()

    @patch("apps.feed_import.views.ProcessOPML.delay")
    def test_rejects_a_text_file_that_is_not_opml(self, delay):
        response = self.client.post(
            "/import/opml_upload",
            {"file": SimpleUploadedFile("subscriptions.opml", b"just some notes, not xml")},
        )
        body = json.loads(response.content)

        self.assertEqual(body["code"], -1, body)
        self.assertIn("Couldn't parse XML file", body["message"])
        delay.assert_not_called()


class Test_OpmlExport(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("opml-exporter", "exporter@example.com", "exporter-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.force_login(self.user)

    def test_anonymous_cannot_download_the_fallback_account(self):
        response = Client(HTTP_USER_AGENT=UA).get("/import/opml_export")

        self.assertEqual(response.status_code, 403)

    def test_a_logged_in_reader_still_gets_the_file(self):
        # OPMLExporter runs inside the timelimit thread, which opens its own connection
        # outside the test transaction, so stand it in rather than touch the database.
        with patch("apps.feed_import.views.OPMLExporter") as exporter:
            exporter.return_value.process.return_value = '<?xml version="1.0"?><opml version="1.0" />'
            response = self.client.get("/import/opml_export")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<opml", response.content)

    def test_export_rejects_an_unknown_user_id(self):
        self.user.is_staff = True
        self.user.save()

        response = self.client.get("/import/opml_export?user_id=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Unknown user_id.")
