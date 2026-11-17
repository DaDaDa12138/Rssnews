"""Profile tasks: user lifecycle management including onboarding and cleanup."""

from apps.profile.models import Profile
from apps.reader.models import UserSubscription, UserSubscriptionFolders
from newsblur_web.celeryapp import app


@app.task(name="email-new-user")
def EmailNewUser(user_id):
    user_profile = Profile.objects.get(user__pk=user_id)
    user_profile.send_new_user_email()


@app.task()
def FetchArchiveFeedsForUser(user_id):
    # subs = UserSubscription.objects.filter(user=user_id)
    # user_profile = Profile.objects.get(user__pk=user_id)
    # logging.user(user_profile.user, f"~FCBeginning archive feed fetches for ~SB~FG{subs.count()} feeds~SN...")

    UserSubscription.fetch_archive_feeds_for_user(user_id)


@app.task()
def FetchArchiveFeedsChunk(feed_ids, user_id=None, backfill_id=None):
    # logging.debug(" ---> Fetching archive stories: %s for %s" % (feed_ids, user_id))
    UserSubscription.fetch_archive_feeds_chunk(feed_ids, user_id, backfill_id)


class ArchiveBackfillDispatchTask(app.Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # apps/profile/tasks.py: Out of retries, so the backfill is abandoned. Drop it and free the
        # user's claim, so a later upgrade event can start a new backfill instead of being skipped.
        user_id = kwargs.get("user_id", args[0] if args else None)
        if user_id:
            UserSubscription.abandon_archive_backfill(user_id, kwargs.get("start_time"))


# apps/profile/tasks.py: Queues the next batch of a user's archive backfill. A broker error partway
# through leaves the unqueued feeds on the user's list, so the retry picks up where it stopped.
@app.task(
    base=ArchiveBackfillDispatchTask,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 8},
)
def DispatchArchiveBackfill(user_id, start_time, starting_story_count):
    UserSubscription.dispatch_archive_backfill(user_id, start_time, starting_story_count)


# apps/profile/tasks.py: Acknowledged when it starts, not when it ends. It runs up to an hour syncing a
# big subscription list, and an unacknowledged task is handed to another worker once the broker's one
# hour visibility timeout passes, which would send the archive email twice.
@app.task(acks_late=False)
def FinishFetchArchiveFeeds(results, user_id, start_time, starting_story_count, rechecks=0):
    # logging.debug(" ---> Fetching archive stories finished for %s" % (user_id))

    # Waits for the backfill's walks to end, and runs once per backfill (apps/reader/models.py).
    if not UserSubscription.archive_backfill_ready_to_finish(
        user_id, start_time, starting_story_count, rechecks
    ):
        return

    ending_story_count, pre_archive_count = UserSubscription.finish_fetch_archive_feeds(
        user_id, start_time, starting_story_count
    )



@app.task(name="cleanup-user")
def CleanupUser(user_id):
    UserSubscription.trim_user_read_stories(user_id)
    UserSubscription.verify_feeds_scheduled(user_id)
    Profile.count_all_feed_subscribers_for_user(user_id)
    UserSubscriptionFolders.add_missing_feeds_for_user(user_id)
    UserSubscriptionFolders.compact_for_user(user_id)
    UserSubscription.refresh_stale_feeds(user_id)
