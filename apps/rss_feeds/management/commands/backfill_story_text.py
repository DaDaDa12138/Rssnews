from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.rss_feeds.models import MStory, story_text_for_search


class Command(BaseCommand):
    help = (
        "Fill MStory.story_text, the plain-text column used by body: search. "
        "Run after migrating and before enabling SEARCH_FREE_TEXT_INCLUDES_BODY "
        "on an existing database. Re-running is safe; by default it only visits "
        "rows whose story_text is null or empty."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Rows fetched per batch (default: 500)",
        )
        parser.add_argument(
            "--feed",
            type=int,
            default=None,
            help="Only backfill stories from this feed id",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_rows",
            help="Recompute every row, not only rows with a missing story_text",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Count rows and print samples without writing",
        )

    def handle(self, *args, **options):
        batch_size = max(1, options["batch_size"])
        queryset = MStory.objects.all().order_by("pk")
        if options["feed"] is not None:
            queryset = queryset.filter(story_feed_id=options["feed"])
        if not options["all_rows"]:
            queryset = queryset.filter(Q(story_text__isnull=True) | Q(story_text=""))

        total = 0
        last_pk = 0
        while True:
            batch = list(queryset.filter(pk__gt=last_pk)[:batch_size])
            if not batch:
                break
            last_pk = batch[-1].pk
            updates = []
            for story in batch:
                # story_latest_content is the full current article on an update;
                # story_content is the original. story_content_str handles the
                # compressed column and returns "" for corrupt data.
                content = story.story_latest_content or story.story_content
                if not content:
                    content = story.story_content_str
                updates.append((story.pk, story_text_for_search(content)))

            if options["dry_run"]:
                for pk, text in updates[:3]:
                    self.stdout.write(" DRYRUN story %s -> %s chars" % (pk, len(text)))
            else:
                for pk, text in updates:
                    MStory.objects.filter(pk=pk).update(story_text=text)
            total += len(updates)
            if options["verbosity"] > 1:
                self.stdout.write(" Processed %s stories" % total)

        if options["dry_run"]:
            self.stdout.write(" DRYRUN: %s stories need story_text" % total)
        else:
            self.stdout.write(" ---> Updated %s stories" % total)
