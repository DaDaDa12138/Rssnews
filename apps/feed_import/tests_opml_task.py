"""A redelivered ProcessOPML task must not email the user twice (apps/feed_import/tasks.py)."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from apps.feed_import.models import UploadedOPML
from apps.feed_import.tasks import ProcessOPML, _process_uploaded_opml
from apps.reader.models import UserSubscription
from apps.rss_feeds.models import Feed

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline type="rss" text="Probe" xmlUrl="http://opml-task.example.com/feed" />
  </body>
</opml>
"""

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(EMAIL_BACKEND=LOCMEM)
class Test_OpmlTaskIdempotency(TestCase):
    def setUp(self):
        mail.outbox = []
        self.user = User.objects.create_user("opmltask", "opmltask@example.com", "opmltask-password")
        self.user.profile.send_emails = True
        self.user.profile.save()
        Feed.objects.create(feed_address="http://opml-task.example.com/feed", feed_title="Probe")
        self.uploaded = UploadedOPML.objects.create(user_id=self.user.pk, opml_file=OPML)

    def process(self, uploaded_opml):
        # The fetch queue is not what this test is about, and it reaches redis.
        with patch.object(UserSubscription, "queue_new_feeds"), patch.object(
            UserSubscription, "refresh_stale_feeds"
        ):
            _process_uploaded_opml(self.user, uploaded_opml)

    def test_processing_the_same_document_twice_sends_one_email(self):
        self.process(self.uploaded)
        self.process(self.uploaded)

        self.assertEqual(len(mail.outbox), 1, [message.subject for message in mail.outbox])
        self.uploaded.refresh_from_db()
        self.assertIsNotNone(self.uploaded.finished_email_sent_date)

    def test_the_import_itself_stays_idempotent(self):
        self.process(self.uploaded)
        self.process(self.uploaded)

        self.assertEqual(UserSubscription.objects.filter(user=self.user).count(), 1)

    def test_a_second_upload_still_sends_its_own_email(self):
        self.process(self.uploaded)
        second = UploadedOPML.objects.create(user_id=self.user.pk, opml_file=OPML)
        self.process(second)

        self.assertEqual(len(mail.outbox), 2)

    def test_a_redelivered_task_sends_nothing_extra(self):
        with patch.object(UserSubscription, "queue_new_feeds"), patch.object(
            UserSubscription, "refresh_stale_feeds"
        ):
            ProcessOPML.apply(args=[self.user.pk, str(self.uploaded.pk)])
            ProcessOPML.apply(args=[self.user.pk, str(self.uploaded.pk)])

        self.assertEqual(len(mail.outbox), 1)
