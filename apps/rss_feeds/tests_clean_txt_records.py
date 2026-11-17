"""clean_txt_records resolves its DNSimple credentials from options, env or settings."""

import os
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

COMMAND = "apps.rss_feeds.management.commands.clean_txt_records.requests"


def txt_record(record_id, name, record_type="TXT"):
    return {"id": record_id, "name": name, "type": record_type, "content": "token-%s" % record_id}


def response(payload, status_code=200):
    mock = Mock()
    mock.status_code = status_code
    mock.text = "payload"
    mock.json.return_value = payload
    return mock


class Test_CleanTxtRecords(SimpleTestCase):
    def test_asks_for_credentials_when_none_are_configured(self):
        with override_settings(DNSIMPLE_TOKEN=""):
            with patch.dict(os.environ, {"DNSIMPLE_API_TOKEN": "", "DNSIMPLE_ACCOUNT_ID": ""}):
                with self.assertRaises(CommandError) as caught:
                    call_command("clean_txt_records", stdout=StringIO())

        self.assertIn("DNSIMPLE_API_TOKEN", str(caught.exception))

    @patch(COMMAND)
    def test_deletes_only_the_acme_challenge_records(self, requests_mock):
        requests_mock.get.return_value = response(
            {
                "data": [
                    txt_record(1, "_acme-challenge"),
                    txt_record(2, "www"),
                    txt_record(3, "_acme-challenge-old"),
                ],
                "pagination": {"current_page": 1, "total_pages": 1},
            }
        )
        requests_mock.delete.return_value = response({}, status_code=204)

        call_command("clean_txt_records", token="tok-123", account_id="42", stdout=StringIO())

        self.assertEqual(
            requests_mock.get.call_args[0][0], "https://api.dnsimple.com/v2/42/zones/newsblur.com/records?page=1"
        )
        self.assertEqual(requests_mock.get.call_args[1]["headers"]["Authorization"], "Bearer tok-123")
        self.assertEqual(
            [call[0][0] for call in requests_mock.delete.call_args_list],
            [
                "https://api.dnsimple.com/v2/42/zones/newsblur.com/records/1",
                "https://api.dnsimple.com/v2/42/zones/newsblur.com/records/3",
            ],
        )

    @patch(COMMAND)
    def test_reads_every_page_of_records(self, requests_mock):
        requests_mock.get.side_effect = [
            response(
                {"data": [txt_record(1, "_acme-challenge")], "pagination": {"current_page": 1, "total_pages": 2}}
            ),
            response(
                {"data": [txt_record(2, "_acme-challenge")], "pagination": {"current_page": 2, "total_pages": 2}}
            ),
        ]
        requests_mock.delete.return_value = response({}, status_code=204)

        call_command("clean_txt_records", token="tok-123", account_id="42", stdout=StringIO())

        self.assertEqual(requests_mock.get.call_count, 2)
        self.assertTrue(requests_mock.get.call_args[0][0].endswith("records?page=2"))

    @patch(COMMAND)
    def test_falls_back_to_the_environment(self, requests_mock):
        requests_mock.get.return_value = response({}, status_code=500)

        with patch.dict(os.environ, {"DNSIMPLE_API_TOKEN": "env-token", "DNSIMPLE_ACCOUNT_ID": "77"}):
            call_command("clean_txt_records", stdout=StringIO(), stderr=StringIO())

        self.assertTrue(requests_mock.get.call_args[0][0].startswith("https://api.dnsimple.com/v2/77/zones/"))

    @patch(COMMAND)
    def test_falls_back_to_the_setting_for_the_token(self, requests_mock):
        requests_mock.get.return_value = response({}, status_code=500)

        with override_settings(DNSIMPLE_TOKEN="settings-token"):
            with patch.dict(os.environ, {"DNSIMPLE_API_TOKEN": "", "DNSIMPLE_ACCOUNT_ID": "77"}):
                call_command("clean_txt_records", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(requests_mock.get.call_args[1]["headers"]["Authorization"], "Bearer settings-token")
