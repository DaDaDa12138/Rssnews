"""One registry for the six trained-classifier tables.

Three views used to spell the same six models out by hand: the trainer payload in
apps/reader/views.py all_classifiers, and the counters and bulk delete in
apps/profile/views.py. Adding a classifier type meant editing all three, and a
missed one showed up as a type that counted but never deleted.

Every table stores one text column plus a score. "is_regex" marks rows written as a
regular expression, and the tag and feed tables have no such column. "scope" is
"feed" unless the row was trained for a whole folder or for everything at once.
"""

from apps.analyzer.models import (
    MClassifierAuthor,
    MClassifierFeed,
    MClassifierTag,
    MClassifierText,
    MClassifierTitle,
    MClassifierUrl,
)


class ClassifierTable:
    """One trained-classifier table and the names the trainer uses for it."""

    __slots__ = ("key", "model", "text_field", "has_regex", "collection")

    def __init__(self, key, model, text_field, has_regex, collection):
        self.key = key
        self.model = model
        self.text_field = text_field
        self.has_regex = has_regex
        self.collection = collection

    def __repr__(self):
        return "<ClassifierTable %s>" % self.key


# Order matters: the trainer payload lists titles before authors before tags, and the
# delete endpoint reports counts in this order.
CLASSIFIER_TABLES = (
    ClassifierTable("title", MClassifierTitle, "title", True, "titles"),
    ClassifierTable("author", MClassifierAuthor, "author", True, "authors"),
    ClassifierTable("tag", MClassifierTag, "tag", False, "tags"),
    ClassifierTable("text", MClassifierText, "text", True, "texts"),
    ClassifierTable("feed", MClassifierFeed, None, False, "feeds"),
    ClassifierTable("url", MClassifierUrl, "url", True, "urls"),
)


def trained(user_id):
    """Every trained row for a user, keyed by table key."""
    return {
        table.key: list(table.model.objects.filter(user_id=user_id, score__ne=0))
        for table in CLASSIFIER_TABLES
    }


def trainer_entry(table, classifier):
    """The trainer JSON for one row: its text, score, regex flag and scope."""
    entry = {table.text_field: getattr(classifier, table.text_field), "score": classifier.score}
    if table.has_regex:
        entry["is_regex"] = getattr(classifier, "is_regex", False)
    entry["scope"] = getattr(classifier, "scope", "feed")
    entry["folder_name"] = getattr(classifier, "folder_name", "")
    return entry


def scoped_collections():
    """The trainer's folder and global buckets, which have no feed-scoped equivalent."""
    return {table.collection: [] for table in CLASSIFIER_TABLES if table.text_field}


def category(name):
    """Map a category name ("title", "title_regex") to its table and query filters."""
    for table in CLASSIFIER_TABLES:
        if not table.has_regex:
            if name == table.key:
                return table, {}
            continue
        if name == table.key:
            return table, {"is_regex__ne": True}
        if name == table.key + "_regex":
            return table, {"is_regex": True}
    return None, {}


def counts(user_id):
    """Trained rows per category, keyed the same way as the delete endpoint."""
    counted = {}
    for table in CLASSIFIER_TABLES:
        if table.has_regex:
            counted[table.key] = table.model.objects.filter(user_id=user_id, is_regex__ne=True).count()
            counted[table.key + "_regex"] = table.model.objects.filter(user_id=user_id, is_regex=True).count()
        else:
            counted[table.key] = table.model.objects.filter(user_id=user_id).count()
    return counted


def delete_categories(user_id, categories):
    """Delete the named categories, returning how many rows each one held."""
    deleted = {}
    for name in categories:
        table, filters = category(name)
        if table is None:
            continue
        queryset = table.model.objects.filter(user_id=user_id, **filters)
        deleted[name] = queryset.count()
        queryset.delete()
    return deleted
