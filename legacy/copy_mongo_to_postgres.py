"""One-off copy of the Mongo collections into the Postgres tables that replaced them.

This script needs pymongo, which is no longer in config/requirements.txt because nothing at
runtime touches Mongo any more. Install it just for the copy:
    docker exec -u 1000 -e HOME=/tmp -t newsblur_web uv pip install --python /venv/bin/python pymongo

Run it inside the web container while the old Mongo container is still around:
    docker exec -u 1000 -e HOME=/tmp -t newsblur_web python legacy/copy_mongo_to_postgres.py
"""
import datetime
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsblur_web.settings")

import django

django.setup()

from pymongo import MongoClient

from apps.analyzer.models import (
    MClassifierAuthor,
    MClassifierFeed,
    MClassifierTag,
    MClassifierText,
    MClassifierTitle,
    MClassifierUrl,
)
from apps.feed_import.models import UploadedOPML
from apps.profile.models import MCustomStyling, MDashboardRiver, MPremiumTrial, MSentEmail
from apps.reader.models import MCustomFeedIcon, MFolderAutoMarkRead, MFolderIcon
from apps.rss_feeds.models import (
    MFeedIcon,
    MFeedPage,
    MFetchHistory,
    MMergeFeedsPrivateInventory,
    MStarredStory,
    MStarredStoryCounts,
    MStory,
)

# (collection, model, {mongo key: django field}) - "_id" maps to None when the new table has its
# own integer primary key, and to the natural key column where Mongo used the feed id as _id.
COLLECTIONS = [
    ("stories", MStory, {}),
    ("starred_stories", MStarredStory, {}),
    ("starred_stories_counts", MStarredStoryCounts, {}),
    ("feed_icons", MFeedIcon, {"_id": "feed_id"}),
    ("feed_pages", MFeedPage, {"_id": "feed_id"}),
    ("fetch_history", MFetchHistory, {}),
    ("merge_feeds_private_inventory", MMergeFeedsPrivateInventory, {}),
    ("dashboard_river", MDashboardRiver, {}),
    ("sent_emails", MSentEmail, {}),
    ("premium_trials", MPremiumTrial, {}),
    ("custom_styling", MCustomStyling, {}),
    ("folder_icons", MFolderIcon, {}),
    ("custom_feed_icons", MCustomFeedIcon, {}),
    ("folder_auto_mark_read", MFolderAutoMarkRead, {}),
    ("uploaded_opml", UploadedOPML, {}),
    ("classifier_title", MClassifierTitle, {}),
    ("classifier_url", MClassifierUrl, {}),
    ("classifier_text", MClassifierText, {}),
    ("classifier_author", MClassifierAuthor, {}),
    ("classifier_tag", MClassifierTag, {}),
    ("classifier_feed", MClassifierFeed, {}),
]


def clean(value):
    """BSON values the Django fields do not accept as-is."""
    if isinstance(value, datetime.datetime):
        # Mongo hands back aware UTC datetimes; this project runs with USE_TZ = False.
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value
    return value


def copy_one(db, collection_name, model, rename):
    collection = db[collection_name]
    field_names = {f.name for f in model._meta.concrete_fields if not f.auto_created}
    rows = []
    for doc in collection.find({}):
        kwargs = {}
        for key, value in doc.items():
            field = rename.get(key, key)
            if not field or field == "id" or field not in field_names:
                continue
            kwargs[field] = clean(value)
        # A None for a NOT NULL column (Mongo happily stored a missing key) would abort the
        # bulk insert, so let the field default stand in for it.
        for field in model._meta.concrete_fields:
            if field.name in kwargs and kwargs[field.name] is None and not field.null:
                kwargs.pop(field.name)
        rows.append(model(**kwargs))
    if not rows:
        print("%-32s mongo %4d  copied 0" % (collection_name, collection.estimated_document_count()))
        return 0
    model.objects.bulk_create(rows, batch_size=200, ignore_conflicts=True)
    print("%-32s mongo %4d  copied %4d" % (collection_name, len(rows), model.objects.count()))
    return len(rows)


def main():
    client = MongoClient(os.environ.get("MONGO_HOST", "newsblur_db_mongo"), 29019)
    db = client[os.environ.get("MONGO_DB_NAME", "newsblur")]
    total = 0
    for collection_name, model, rename in COLLECTIONS:
        total += copy_one(db, collection_name, model, rename)
    print("rows offered to Postgres: %d" % total)


if __name__ == "__main__":
    main()
