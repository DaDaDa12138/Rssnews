from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rss_feeds", "0005_storyfilter"),
    ]

    operations = [
        # icontains over story_text needs pg_trgm; the GIN index is added in the
        # next migration with CREATE INDEX CONCURRENTLY so this one stays atomic.
        TrigramExtension(),
        migrations.AddField(
            model_name="mstory",
            name="story_text",
            field=models.TextField(blank=True, null=True),
        ),
    ]
