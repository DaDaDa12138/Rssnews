"""Helpers that normalise the labels used in reader load logging."""


def normalize_reader_metrics_source(source):
    if source in {"feed_request", "river_request", "score_recalc"}:
        return source
    return "other"


def normalize_reader_metrics_read_filter(read_filter, query=False):
    if query:
        return "query"
    if read_filter in {"all", "unread", "starred"}:
        return read_filter
    return "other"
