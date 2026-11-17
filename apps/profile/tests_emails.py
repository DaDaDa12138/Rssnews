"""Emails record themselves only after a successful send (apps/profile/models.py)."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from apps.profile.models import MSentEmail

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
SEND = "django.core.mail.EmailMultiAlternatives.send"


@override_settings(EMAIL_BACKEND=LOCMEM)
class Test_NewUserEmail(TestCase):
    def setUp(self):
        mail.outbox = []
        self.user = User.objects.create_user("mailer", "mailer@example.com", "mailer-password")
        self.user.profile.send_emails = True
        self.user.profile.save()

    def records(self):
        return MSentEmail.objects.filter(receiver_user_id=self.user.pk, email_type="new_user")

    def test_the_second_send_is_skipped(self):
        self.user.profile.send_new_user_email()
        self.user.profile.send_new_user_email()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.records().count(), 1)

    def test_a_failed_send_leaves_no_record(self):
        with patch(SEND, side_effect=RuntimeError("smtp down")):
            with self.assertRaises(RuntimeError):
                self.user.profile.send_new_user_email()
        self.assertFalse(self.records().exists())

        # The redelivered task must still be able to welcome the user.
        self.user.profile.send_new_user_email()
        self.assertEqual(len(mail.outbox), 1)

    def test_an_empty_address_sends_nothing(self):
        self.user.email = ""
        self.user.save()
        self.user.profile.send_new_user_email()

        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(self.records().exists())


@override_settings(EMAIL_BACKEND=LOCMEM)
class Test_OpmlExportEmail(TestCase):
    def setUp(self):
        mail.outbox = []
        self.user = User.objects.create_user("exporter", "exporter@example.com", "exporter-password")

    def records(self):
        return MSentEmail.objects.filter(receiver_user_id=self.user.pk, email_type="opml_export")

    def test_the_send_is_recorded(self):
        self.user.profile.send_opml_export_email(force=False)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.records().count(), 1)

    def test_the_daily_guard_holds(self):
        self.user.profile.send_opml_export_email(force=False)
        self.user.profile.send_opml_export_email(force=False)

        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_send_does_not_burn_the_daily_guard(self):
        with patch(SEND, side_effect=RuntimeError("smtp down")):
            with self.assertRaises(RuntimeError):
                self.user.profile.send_opml_export_email(force=False)
        self.assertFalse(self.records().exists())

        self.user.profile.send_opml_export_email(force=False)
        self.assertEqual(len(mail.outbox), 1)
