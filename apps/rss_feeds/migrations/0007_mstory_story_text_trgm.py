from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("rss_feeds", "0006_mstory_story_text"),
    ]

    operations = [
        # Django cannot emit the opclass syntax PostgreSQL needs for an
        # expression index: it wraps the expression and the opclass together,
        # producing gin (((UPPER(story_text)) gin_trgm_ops)). Build the index
        # with raw SQL instead. The state operation keeps Django's migration
        # graph in sync with MStory.Meta.indexes, which declares the same index
        # name. apps/rss_feeds/migrations/0007_mstory_story_text_trgm.py
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="mstory",
                    index=GinIndex(
                        fields=["story_text"],
                        name="stories_story_text_trgm",
                        opclasses=["gin_trgm_ops"],
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'CREATE INDEX CONCURRENTLY "stories_story_text_trgm" '
                        'ON "stories" USING gin ((UPPER("story_text")) gin_trgm_ops);'
                    ),
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "stories_story_text_trgm";',
                ),
            ],
        ),
    ]
