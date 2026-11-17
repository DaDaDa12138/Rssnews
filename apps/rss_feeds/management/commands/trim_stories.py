import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.rss_feeds.models import Feed, MStory


class Command(BaseCommand):
    help = (
        "Enforce the story retention caps on every feed: the absolute per-feed ceiling and the "
        "age cap (STORY_RETENTION_DAYS, keeping the newest STORY_RETENTION_MIN_PER_FEED). The "
        "daily trim-stories task runs the same sweep; --dry-run prints what it would delete."
    )

    def add_arguments(self, parser):
        parser.add_argument("-f", "--feed", dest="feed", type=int, default=None, help="Only this feed id")
        parser.add_argument("--days", type=int, default=None, help="Override STORY_RETENTION_DAYS")
        parser.add_argument("--limit", type=int, default=None, help="Only the first N feeds")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Count what would go without deleting anything",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else settings.STORY_RETENTION_DAYS
        feeds = Feed.objects.all().order_by("pk")
        if options["feed"]:
            feeds = feeds.filter(pk=options["feed"])
        if options["limit"]:
            feeds = feeds[: options["limit"]]

        min_keep = settings.STORY_RETENTION_MIN_PER_FEED
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days) if days and days > 0 else None
        total = 0

        for feed in feeds:
            stored = MStory.objects(story_feed_id=feed.pk).count()
            ceiling = feed.story_retention_ceiling()
            old = 0
            if cutoff_date:
                old = MStory.objects(story_feed_id=feed.pk, story_date__lt=cutoff_date).count()
            if stored <= ceiling and not old:
                continue
            if options["dry_run"]:
                self.stdout.write(
                    " DRYRUN feed %s: %s stories, ceiling %s, %s older than %s days, keeps newest %s (%s)"
                    % (feed.pk, stored, ceiling, old, days, min_keep, feed.feed_title[:40])
                )
                continue
            removed = feed.enforce_story_retention(verbose=options["verbosity"] > 1, days=days)
            total += removed
            if removed:
                self.stdout.write(" Feed %s: %s stories trimmed" % (feed.pk, removed))

        if options["dry_run"]:
            self.stdout.write(" DRYRUN: nothing deleted")
        else:
            self.stdout.write(" ---> Deleted %s stories" % total)
