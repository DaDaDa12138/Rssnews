"""The per-phase split appended to the feed fetcher's "Processed in" log line."""

from django.test import SimpleTestCase

from utils.feed_fetcher import FeedFetcherWorker


class Test_PhaseTimings(SimpleTestCase):
    def test_names_only_the_phases_that_ran(self):
        timings = FeedFetcherWorker.phase_timings(0.1234, 0.5, None, None)

        self.assertEqual(timings, " ~FY[fetch 0.12s, process 0.50s]~SN")

    def test_says_nothing_when_no_phase_ran(self):
        self.assertEqual(FeedFetcherWorker.phase_timings(None, None, None, None), "")

    def test_keeps_the_phases_in_pipeline_order(self):
        timings = FeedFetcherWorker.phase_timings(1.0, 2.0, 0.25, 0.05)

        self.assertEqual(timings, " ~FY[fetch 1.00s, process 2.00s, page 0.25s, icon 0.05s]~SN")

    def test_a_feed_that_stopped_after_fetching_still_reports(self):
        # A feed that returns FEED_SAME or FEED_ERRPARSE never reaches process, page or icon.
        timings = FeedFetcherWorker.phase_timings(0.4, None, None, None)

        self.assertEqual(timings, " ~FY[fetch 0.40s]~SN")

    def test_a_feed_under_the_threshold_is_not_slow(self):
        self.assertFalse(FeedFetcherWorker.is_slow_feed(4.99))

    def test_a_feed_at_the_threshold_counts_as_slow(self):
        self.assertTrue(FeedFetcherWorker.is_slow_feed(FeedFetcherWorker.SLOW_FEED_SECONDS))

    def test_a_feed_that_never_finished_is_not_reported_as_slow(self):
        self.assertFalse(FeedFetcherWorker.is_slow_feed(None))
