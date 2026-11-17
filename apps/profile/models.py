"""User profile models: Profile and email preferences.

This is a single-user, personal edition. There are no subscription tiers, so the
profile only carries reading preferences and account metadata.
"""

import datetime
import hashlib
import re
import time

import redis
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.db.utils import DatabaseError
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext

from apps.feed_import.models import OPMLExporter
from apps.reader.models import RUserStory, UserSubscription
from apps.rss_feeds.models import Feed, MStarredStory
from utils import json_functions as json
from utils import log as logging
from utils.feed_functions import chunks
from utils.documents import LegacyDocument
from utils.languages import in_account_language
from utils.user_functions import generate_secret_token
from vendor.timezones.fields import TimeZoneField


class Profile(models.Model):
    user = models.OneToOneField(User, unique=True, related_name="profile", on_delete=models.CASCADE)
    send_emails = models.BooleanField(default=True)
    preferences = models.TextField(default="{}")
    # models.py keeps acquisition language immutable; current device language can change independently.
    signup_language = models.CharField(max_length=16, null=True, blank=True)
    last_read_language = models.CharField(max_length=16, null=True, blank=True)
    view_settings = models.TextField(default="{}")
    collapsed_folders = models.TextField(default="[]")
    feed_pane_size = models.IntegerField(default=282)
    days_of_unread = models.IntegerField(default=settings.DAYS_OF_UNREAD, blank=True, null=True)
    tutorial_finished = models.BooleanField(default=False)
    hide_getting_started = models.BooleanField(default=False, null=True, blank=True)
    has_setup_feeds = models.BooleanField(default=False, null=True, blank=True)
    has_found_friends = models.BooleanField(default=False, null=True, blank=True)
    has_trained_intelligence = models.BooleanField(default=False, null=True, blank=True)
    last_seen_on = models.DateTimeField(default=datetime.datetime.now)
    last_seen_ip = models.CharField(max_length=50, blank=True, null=True)
    # The language this account's devices last asked for, kept by apps/profile/language.py so emails reach
    # Automatic users in it (utils/languages.py:account_language).
    last_seen_language = models.CharField(max_length=16, blank=True, null=True)
    dashboard_date = models.DateTimeField(default=datetime.datetime.now)
    timezone = TimeZoneField(default="America/New_York")
    secret_token = models.CharField(max_length=12, blank=True, null=True)
    def __str__(self):
        return "%s <%s>" % (self.user, self.user.email)

    @property
    def unread_cutoff(self):
        """Everything older than the profile's unread window counts as read."""
        days = self.days_of_unread or settings.DAYS_OF_UNREAD
        return datetime.datetime.utcnow() - datetime.timedelta(days=days)

    def canonical(self):
        return {
            "preferences": json.decode(self.preferences),
            "tutorial_finished": self.tutorial_finished,
            "hide_getting_started": self.hide_getting_started,
            "has_setup_feeds": self.has_setup_feeds,
            "has_found_friends": self.has_found_friends,
            "has_trained_intelligence": self.has_trained_intelligence,
            "dashboard_date": self.dashboard_date,
        }

    def save(self, *args, **kwargs):
        if not self.secret_token:
            self.secret_token = generate_secret_token(self.user.username, 12)
        try:
            super(Profile, self).save(*args, **kwargs)
        except DatabaseError as e:
            print(f" ---> Profile not saved: {e}")

    def delete_user(self, confirm=False, fast=False):
        if not confirm:
            print(" ---> You must pass confirm=True to delete this user.")
            return

        logging.user(self.user, "Deleting user: %s / %s" % (self.user.email, self.user.profile.last_seen_ip))
        starred_stories = MStarredStory.objects.filter(user_id=self.user.pk)
        logging.user(self.user, "Deleting %s starred stories." % starred_stories.count())
        starred_stories.delete()

        logging.user(self.user, "Deleting user: %s" % self.user)
        self.user.delete()

    def activate_free(self):
        if self.user.is_active:
            return

        self.user.is_active = True
        self.user.save()
        self.send_new_user_queue_email()

    def preference_value(self, key, default=None):
        preferences = json.decode(self.preferences)
        return preferences.get(key, default)

    def update_email(self, new_email):
        if self.user.email == new_email:
            return

        self.user.email = new_email
        self.user.save()

    @classmethod
    def clear_dead_spammers(self, days=30, confirm=False):
        users = User.objects.filter(
            date_joined__gte=datetime.datetime.now() - datetime.timedelta(days=days)
        ).order_by("-date_joined")
        usernames = set()
        numerics = re.compile(r"[0-9]+")
        for user in users:
            opens = UserSubscription.objects.filter(user=user).aggregate(sum=Sum("feed_opens"))["sum"]
            reads = RUserStory.read_story_count(user.pk)
            has_numbers = numerics.search(user.username)

            try:
                has_profile = user.profile.last_seen_ip
            except Profile.DoesNotExist:
                usernames.add(user.username)
                print(
                    " ---> Missing profile: %-20s %-30s %-6s %-6s" % (user.username, user.email, opens, reads)
                )
                continue

            if opens is None and not reads and has_numbers:
                usernames.add(user.username)
                print(" ---> Numerics: %-20s %-30s %-6s %-6s" % (user.username, user.email, opens, reads))
            elif not has_profile:
                usernames.add(user.username)
                print(" ---> No IP: %-20s %-30s %-6s %-6s" % (user.username, user.email, opens, reads))

        if not confirm:
            return usernames

        for username in usernames:
            try:
                u = User.objects.get(username=username)
            except User.DoesNotExist:
                continue
            u.profile.delete_user(confirm=True)

        RNewUserQueue.user_count()
        RNewUserQueue.activate_all()

    @classmethod
    def count_feed_subscribers(self, feed_id=None, user_id=None, verbose=True):
        SUBSCRIBER_EXPIRE = datetime.datetime.now() - datetime.timedelta(days=settings.SUBSCRIBER_EXPIRE)
        r = redis.Redis(connection_pool=settings.REDIS_FEED_SUB_POOL)
        entire_feed_counted = False

        if verbose:
            feed = Feed.get_by_id(feed_id)
            logging.debug(
                "   ---> [%-30s] ~SN~FBCounting subscribers for feed:~SB~FM%s~SN~FB user:~SB~FM%s"
                % (feed.log_title[:30], feed_id, user_id)
            )

        if feed_id:
            feed_ids = [feed_id]
        elif user_id:
            feed_ids = [
                us["feed_id"]
                for us in UserSubscription.objects.filter(user=user_id, active=True).values("feed_id")
            ]
        else:
            assert False, "feed_id or user_id required"

        if feed_id and not user_id:
            entire_feed_counted = True

        for feed_id in feed_ids:
            total = 0
            premium = 0
            active = 0
            active_premium = 0
            key = "s:%s" % feed_id
            premium_key = "sp:%s" % feed_id

            if user_id:
                active = (
                    UserSubscription.objects.filter(feed_id=feed_id, user_id=user_id)
                    .values_list("active", flat=True)
                    .first()
                )
                user_active_feeds = dict([(user_id, active)])
            else:
                user_active_feeds = dict(
                    [
                        (us.user_id, us.active)
                        for us in UserSubscription.objects.filter(feed_id=feed_id).only("user", "active")
                    ]
                )
            profiles = Profile.objects.filter(user_id__in=list(user_active_feeds.keys())).values(
                "user_id", "last_seen_on"
            )
            feed = Feed.get_by_id(feed_id)

            if entire_feed_counted:
                pipeline = r.pipeline()
                pipeline.delete(key)
                pipeline.delete(premium_key)
                pipeline.execute()

            for profiles_group in chunks(profiles, 20):
                pipeline = r.pipeline()
                for profile in profiles_group:
                    last_seen_on = int(profile["last_seen_on"].strftime("%s"))
                    muted_feed = not bool(user_active_feeds[profile["user_id"]])
                    if muted_feed:
                        last_seen_on = 0
                    pipeline.zadd(key, {profile["user_id"]: last_seen_on})
                    pipeline.zadd(premium_key, {profile["user_id"]: last_seen_on})
                    total += 1
                    premium += 1
                    if profile["last_seen_on"] > SUBSCRIBER_EXPIRE and not muted_feed:
                        active += 1
                        active_premium += 1

                pipeline.execute()

            if entire_feed_counted:
                now = int(datetime.datetime.now().strftime("%s"))
                r.zadd(key, {-1: now})
                r.expire(key, settings.SUBSCRIBER_EXPIRE * 24 * 60 * 60)
                r.zadd(premium_key, {-1: now})
                r.expire(premium_key, settings.SUBSCRIBER_EXPIRE * 24 * 60 * 60)

            logging.info(
                "   ---> [%-30s] ~SN~FBCounting subscribers, storing in ~SBredis~SN: ~FMt:~SB~FM%s~SN a:~SB%s~SN p:~SB%s~SN ap:~SB%s~SN"
                % (feed.log_title[:30], total, active, premium, active_premium)
            )

    @classmethod
    def count_all_feed_subscribers_for_user(self, user):
        r = redis.Redis(connection_pool=settings.REDIS_FEED_SUB_POOL)
        if not isinstance(user, User):
            user = User.objects.get(pk=user)

        active_feed_ids = [
            us["feed_id"]
            for us in UserSubscription.objects.filter(user=user.pk, active=True).values("feed_id")
        ]
        muted_feed_ids = [
            us["feed_id"]
            for us in UserSubscription.objects.filter(user=user.pk, active=False).values("feed_id")
        ]
        logging.user(
            user,
            "~SN~FBRefreshing user last_login_on for ~SB%s~SN/~SB%s subscriptions~SN"
            % (len(active_feed_ids), len(muted_feed_ids)),
        )
        for feed_ids in [active_feed_ids, muted_feed_ids]:
            for feeds_group in chunks(feed_ids, 200):
                pipeline = r.pipeline()
                for feed_id in feeds_group:
                    key = "s:%s" % feed_id
                    premium_key = "sp:%s" % feed_id

                    last_seen_on = int(user.profile.last_seen_on.strftime("%s"))
                    if feed_ids is muted_feed_ids:
                        last_seen_on = 0
                    pipeline.zadd(key, {user.pk: last_seen_on})
                    pipeline.zadd(premium_key, {user.pk: last_seen_on})
                pipeline.execute()

    @in_account_language
    def send_new_user_email(self):
        if not self.user.email or not self.send_emails:
            return

        # apps/profile/models.py: EmailNewUser runs under CELERY_TASK_ACKS_LATE, so a worker that
        # dies after the send gets the task redelivered. Record the send so the retry is a no-op.
        params = dict(receiver_user_id=self.user.pk, email_type="new_user")
        if MSentEmail.objects.filter(**params).exists():
            logging.user(self.user, "~SN~FMNot sending new user email, already sent.")
            return

        user = self.user
        text = render_to_string("mail/email_new_account.txt", locals())
        html = render_to_string("mail/email_new_account.xhtml", locals())
        subject = gettext("Welcome to NewsBlur, %(username)s") % {"username": self.user.username}
        msg = EmailMultiAlternatives(
            subject,
            text,
            from_email="NewsBlur <%s>" % settings.HELLO_EMAIL,
            to=["%s <%s>" % (user, user.email)],
            headers=self.email_unsubscribe_headers(),
        )
        msg.attach_alternative(html, "text/html")
        msg.send()
        MSentEmail.objects.create(**params)

        logging.user(self.user, "~BB~FM~SBSending email for new user: %s" % self.user.email)

    @in_account_language
    def send_opml_export_email(self, reason=None, force=False):
        if not self.user.email:
            return

        emails_sent = MSentEmail.objects.filter(receiver_user_id=self.user.pk, email_type="opml_export")
        day_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        for email in emails_sent:
            if email.date_sent > day_ago and not force:
                logging.user(self.user, "~SN~FMNot sending opml export email, already sent today.")
                return

        exporter = OPMLExporter(self.user)
        opml = exporter.process()

        params = {
            "feed_count": UserSubscription.objects.filter(user=self.user).count(),
            "reason": reason,
        }
        user = self.user
        text = render_to_string("mail/email_opml_export.txt", params)
        html = render_to_string("mail/email_opml_export.xhtml", params)
        subject = gettext("Backup OPML file of your NewsBlur sites")
        filename = "NewsBlur Subscriptions - %s.xml" % datetime.datetime.now().strftime("%Y-%m-%d")
        msg = EmailMultiAlternatives(
            subject,
            text,
            from_email="NewsBlur <%s>" % settings.HELLO_EMAIL,
            to=["%s <%s>" % (user, user.email)],
            headers=self.email_unsubscribe_headers(),
        )
        msg.attach_alternative(html, "text/html")
        msg.attach(filename, opml, "text/xml")
        msg.send()
        # apps/profile/models.py: record after the send so a failed send still allows the retry
        # that the "already sent today" guard would otherwise block for a day.
        MSentEmail.record(receiver_user_id=self.user.pk, email_type="opml_export")

        logging.user(self.user, "~BB~FM~SBSending OPML backup email to: %s" % self.user.email)


    @in_account_language
    def send_forgot_password_email(self, email=None):
        if not self.user.email and not email:
            print("Please provide an email address.")
            return

        if not self.user.email and email:
            self.user.email = email
            self.user.save()

        user = self.user
        text = render_to_string("mail/email_forgot_password.txt", locals())
        html = render_to_string("mail/email_forgot_password.xhtml", locals())
        subject = gettext("Forgot your password on NewsBlur?")
        msg = EmailMultiAlternatives(
            subject,
            text,
            from_email="NewsBlur <%s>" % settings.HELLO_EMAIL,
            to=["%s <%s>" % (user, user.email)],
            headers=self.email_unsubscribe_headers(),
        )
        msg.attach_alternative(html, "text/html")
        msg.send()

        logging.user(self.user, "~BB~FM~SBSending email for forgotten password: %s" % self.user.email)

    @in_account_language
    def send_new_user_queue_email(self, force=False):
        if not self.user.email:
            print("Please provide an email address.")
            return

        params = dict(receiver_user_id=self.user.pk, email_type="new_user_queue")
        try:
            MSentEmail.objects.get(**params)
            if not force:
                # Return if email already sent
                return
        except MSentEmail.DoesNotExist:
            MSentEmail.objects.create(**params)

        user = self.user
        text = render_to_string("mail/email_new_user_queue.txt", locals())
        html = render_to_string("mail/email_new_user_queue.xhtml", locals())
        subject = gettext("Your free account is now ready to go on NewsBlur")
        msg = EmailMultiAlternatives(
            subject,
            text,
            from_email="NewsBlur <%s>" % settings.HELLO_EMAIL,
            to=["%s <%s>" % (user, user.email)],
            headers=self.email_unsubscribe_headers(),
        )
        msg.attach_alternative(html, "text/html")
        msg.send()

        logging.user(self.user, "~BB~FM~SBSending email for new user queue: %s" % self.user.email)

    @in_account_language
    def send_upload_opml_finished_email(self, feed_count):
        if not self.user.email:
            print("Please provide an email address.")
            return

        user = self.user
        text = render_to_string("mail/email_upload_opml_finished.txt", locals())
        html = render_to_string("mail/email_upload_opml_finished.xhtml", locals())
        subject = gettext("Your OPML upload is complete. Get going with NewsBlur!")
        msg = EmailMultiAlternatives(
            subject,
            text,
            from_email="NewsBlur <%s>" % settings.HELLO_EMAIL,
            to=["%s <%s>" % (user, user.email)],
            headers=self.email_unsubscribe_headers(),
        )
        msg.attach_alternative(html, "text/html")
        msg.send()

        logging.user(self.user, "~BB~FM~SBSending email for OPML upload: %s" % self.user.email)

    def autologin_url(self, next=None):
        return reverse("autologin", kwargs={"username": self.user.username, "secret": self.secret_token}) + (
            "?" + next + "=1" if next else ""
        )

    def email_optout_url(self):
        """Tokened two-click unsubscribe link used in email footers. Auto-logs in the
        user, then unsubscribes on a button press (apps/profile/views.py email_optout_token)."""
        return reverse(
            "profile-email-optout-token",
            kwargs={"username": self.user.username, "secret": self.secret_token},
        )

    def email_unsubscribe_headers(self):
        """RFC 8058 one-click unsubscribe headers so mail clients can offer their own
        unsubscribe button. Providers POST to the tokened unsubscribe URL, which
        unsubscribes immediately (apps/profile/views.py email_optout_token)."""
        domain = Site.objects.get_current().domain
        return {
            "List-Unsubscribe": "<https://%s%s>" % (domain, self.email_optout_url()),
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }


def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        logging.user(instance, "~BY~SK~FW~SBNEW USER!~SN")
    else:
        Profile.objects.get_or_create(user=instance)


post_save.connect(create_profile, sender=User)


def change_password(user, old_password, new_password, only_check=False):
    user_db = authenticate(username=user.username, password=old_password)
    if user_db is None:
        blank = blank_authenticate(user.username)
        if blank and not only_check:
            user.set_password(new_password or user.username)
            user.save()
    if user_db is None:
        user_db = authenticate(username=user.username, password=user.username)

    if not user_db:
        return -1
    else:
        if not only_check:
            user_db.set_password(new_password)
            user_db.save()
        return 1


def blank_authenticate(username, password=""):
    try:
        user = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        return

    if user.password == "!":
        return user

    # Provider-only accounts (created by an external sign-in flow) have unusable passwords.
    if not user.has_usable_password():
        return None

    algorithm, salt, hash = user.password.split("$", 2)
    encoded_blank = hashlib.sha1((salt + password).encode(encoding="utf-8")).hexdigest()
    encoded_username = authenticate(username=username, password=username)
    if encoded_blank == hash or encoded_username == user:
        return user


class MSentEmail(LegacyDocument):
    sending_user_id = models.IntegerField(null=True, blank=True)
    receiver_user_id = models.IntegerField(null=True, blank=True)
    email_type = models.TextField(null=True, blank=True)
    date_sent = models.DateTimeField(default=datetime.datetime.now, null=True, blank=True)

    class Meta:
        db_table = "sent_emails"
        indexes = [
            models.Index(fields=['sending_user_id']),
            models.Index(fields=['receiver_user_id']),
            models.Index(fields=['email_type']),
        ]

    def __str__(self):
        sender_user = self.sending_user_id
        if sender_user:
            sender_user = User.objects.get(pk=self.sending_user_id)
        receiver_user = self.receiver_user_id
        if receiver_user:
            receiver_user = User.objects.get(pk=self.receiver_user_id)
        return "%s sent %s email to %s %s" % (
            sender_user,
            self.email_type,
            receiver_user,
            receiver_user.profile if receiver_user else receiver_user,
        )

    @classmethod
    def record(cls, email_type, receiver_user_id, sending_user_id=None):
        cls.objects.create(
            email_type=email_type, receiver_user_id=receiver_user_id, sending_user_id=sending_user_id
        )


class MCustomStyling(LegacyDocument):
    user_id = models.IntegerField(unique=True, null=True, blank=True)
    custom_css = models.TextField(null=True, blank=True)
    custom_js = models.TextField(null=True, blank=True)
    updated_date = models.DateTimeField(default=datetime.datetime.now, null=True, blank=True)

    class Meta:
        db_table = "custom_styling"
        indexes = [
            models.Index(fields=['user_id']),
        ]

    def __str__(self):
        return "%s custom style %s/%s %s" % (
            self.user_id,
            len(self.custom_css) if self.custom_css else "-",
            len(self.custom_js) if self.custom_js else "-",
            self.updated_date,
        )

    def canonical(self):
        return {
            "css": self.custom_css,
            "js": self.custom_js,
        }

    @classmethod
    def get_user(cls, user_id):
        try:
            styling = cls.objects.get(user_id=user_id)
        except cls.DoesNotExist:
            return None

        return styling

    @classmethod
    def save_user(cls, user_id, css, js):
        styling = cls.get_user(user_id)
        if not css and not js:
            if styling:
                styling.delete()
            return

        if not styling:
            styling = cls.objects.create(user_id=user_id)

        styling.custom_css = css
        styling.custom_js = js
        styling.save()


class MDashboardRiver(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    river_id = models.TextField(null=True, blank=True)
    river_side = models.TextField(null=True, blank=True)
    river_order = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "dashboard_river"
        ordering = ['river_order']
        indexes = [
            models.Index(fields=['user_id']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['user_id', 'river_id', 'river_side', 'river_order'], name='uniq_dashboard_river_user_id_river_id_river_side_river_order'),
        ]

    def __str__(self):
        try:
            u = User.objects.get(pk=self.user_id)
        except User.DoesNotExist:
            u = "<missing user>"
        return f"{u} ({self.river_side}/{self.river_order}): {self.river_id}"

    def canonical(self):
        return {
            "river_id": self.river_id,
            "river_side": self.river_side,
            "river_order": self.river_order,
        }

    @classmethod
    def get_user_rivers(cls, user_id):
        return cls.objects(user_id=user_id)

    @classmethod
    def remove_river(cls, user_id, river_side, river_order):
        try:
            river = cls.objects.get(user_id=user_id, river_side=river_side, river_order=river_order)
        except cls.DoesNotExist:
            return

        river.delete()

        for r, river in enumerate(cls.objects.filter(user_id=user_id, river_side=river_side)):
            if river.river_order != r:
                logging.debug(f" ---> Rebalancing {river} from {river.river_order} to {r}")
                river.river_order = r
                river.save()

    @classmethod
    def save_user(cls, user_id, river_id, river_side, river_order):
        try:
            river = cls.objects.get(user_id=user_id, river_side=river_side, river_order=river_order)
        except cls.DoesNotExist:
            river = None

        if not river:
            river = cls.objects.create(
                user_id=user_id, river_id=river_id, river_side=river_side, river_order=river_order
            )

        river.river_id = river_id
        river.river_side = river_side
        river.river_order = river_order
        river.save()


class RNewUserQueue:
    KEY = "new_user_queue"

    @classmethod
    def activate_next(cls):
        count = cls.user_count()
        if not count:
            return

        user_id = cls.pop_user()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logging.debug(
                "~FRCan't activate free account, can't find user ~SB%s~SN. ~FB%s still in queue."
                % (user_id, count - 1)
            )
            return

        logging.user(
            user,
            "~FBActivating free account (%s / %s). %s still in queue."
            % (user.email, user.profile.last_seen_ip, (count - 1)),
        )

        user.profile.activate_free()

    @classmethod
    def activate_all(cls):
        count = cls.user_count()
        if not count:
            logging.debug("~FBNo users to activate, sleeping...")
            return

        for i in range(count):
            cls.activate_next()

    @classmethod
    def add_user(cls, user_id):
        r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)
        now = time.time()

        r.zadd(cls.KEY, {user_id: now})

    @classmethod
    def user_count(cls):
        r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)
        count = r.zcard(cls.KEY)

        return count

    @classmethod
    def pop_user(cls):
        r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)
        user = r.zrange(cls.KEY, 0, 0)[0]
        r.zrem(cls.KEY, user)

        return user


