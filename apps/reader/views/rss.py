"""RSS feeds for saved stories and folders.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403



def starred_stories_rss_feed(request, user_id, secret_token):
    return starred_stories_rss_feed_tag(request, user_id, secret_token, tag_slug=None)



def starred_stories_rss_feed_tag(request, user_id, secret_token, tag_slug):
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        raise Http404

    if tag_slug:
        try:
            tag_counts = MStarredStoryCounts.objects.get(user_id=user_id, slug=tag_slug)
        except MStarredStoryCounts.MultipleObjectsReturned:
            tag_counts = MStarredStoryCounts.objects(user_id=user_id, slug=tag_slug).first()
        except MStarredStoryCounts.DoesNotExist:
            raise Http404
    else:
        _, starred_count = MStarredStoryCounts.user_counts(user.pk, include_total=True)

    data = {}
    if tag_slug:
        # The highlights pseudo-tag has no tag text of its own, so name it explicitly
        # instead of rendering "Saved Stories - None".
        tag_label = tag_counts.tag or ("Highlights" if tag_counts.is_highlights else tag_slug)
        data["title"] = "Saved Stories - %s" % tag_label
    else:
        data["title"] = "Saved Stories"
    data["link"] = "%s%s" % (
        settings.NEWSBLUR_URL,
        reverse("saved-stories-tag", kwargs=dict(tag_name=tag_slug)),
    )
    if tag_slug:
        data["description"] = 'Stories saved by %s on NewsBlur with the tag "%s".' % (
            user.username,
            tag_label,
        )
    else:
        data["description"] = "Stories saved by %s on NewsBlur." % (user.username)
    data["lastBuildDate"] = datetime.datetime.utcnow()
    data["generator"] = "NewsBlur - %s" % settings.NEWSBLUR_URL
    data["docs"] = None
    data["author_name"] = user.username
    data["feed_url"] = "%s%s" % (
        settings.NEWSBLUR_URL,
        reverse(
            "starred-stories-rss-feed-tag",
            kwargs=dict(user_id=user_id, secret_token=secret_token, tag_slug=tag_slug),
        ),
    )
    rss = feedgenerator.Atom1Feed(**data)

    if not tag_slug or not tag_counts.tag:
        starred_stories = MStarredStory.objects(user_id=user.pk).order_by("-starred_date").limit(25)
    elif tag_counts.is_highlights:
        starred_stories = (
            MStarredStory.objects(user_id=user.pk).exclude(highlights=[]).order_by("-starred_date").limit(25)
        )
    else:
        starred_stories = (
            MStarredStory.objects(user_id=user.pk, user_tags__contains=tag_counts.tag)
            .order_by("-starred_date")
            .limit(25)
        )

    starred_stories = Feed.format_stories(starred_stories)

    for starred_story in starred_stories:
        story_data = {
            "title": smart_str(starred_story["story_title"]),
            "link": starred_story["story_permalink"],
            "description": smart_str(starred_story["story_content"]),
            "author_name": starred_story["story_authors"],
            "categories": starred_story["story_tags"],
            "unique_id": starred_story["story_permalink"],
            "pubdate": starred_story["starred_date"],
        }
        rss.add_item(**story_data)

    logging.user(
        request,
        "~FBGenerating ~SB%s~SN's saved story RSS feed (%s, %s stories): ~FM%s"
        % (
            user.username,
            tag_counts.tag if tag_slug else "[All stories]",
            tag_counts.count if tag_slug else starred_count,
            request.META.get("HTTP_USER_AGENT", "")[:24],
        ),
    )
    return HttpResponse(rss.writeString("utf-8"), content_type="application/rss+xml")



@ratelimit_by_url_user(minutes=1, requests=30)
def folder_rss_feed(request, user_id, secret_token, unread_filter, folder_slug):
    # Check cache first (60 second TTL)
    cache_key = f"folder_rss:{user_id}:{folder_slug}:{unread_filter}"
    cached_response = cache.get(cache_key)
    if cached_response:
        return HttpResponse(cached_response, content_type="application/rss+xml")

    domain = Site.objects.get_current().domain
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        raise Http404

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=user)
    feed_ids, folder_title = user_sub_folders.feed_ids_under_folder_slug(folder_slug)
    if not folder_title:
        raise Http404

    usersubs = UserSubscription.subs_for_feeds(user.pk, feed_ids=feed_ids)
    if feed_ids:
        params = {
            "user_id": user.pk,
            "feed_ids": feed_ids,
            "offset": 0,
            "limit": 20,
            "order": "newest",
            "read_filter": "all",
            "cache_prefix": "RSS:",
        }
        story_hashes, unread_feed_story_hashes = UserSubscription.feed_stories(**params)
    else:
        story_hashes = []

    mstories = MStory.objects(story_hash__in=story_hashes).order_by("-story_date")
    stories = Feed.format_stories(mstories)

    filtered_stories = []
    found_feed_ids = list(set([story["story_feed_id"] for story in stories]))
    trained_feed_ids = [sub.feed_id for sub in usersubs if sub.is_trained]
    found_trained_feed_ids = list(set(trained_feed_ids) & set(found_feed_ids))
    if found_trained_feed_ids:
        classifier_feeds = list(
            MClassifierFeed.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids, social_user_id=0)
        )
        classifier_authors = list(MClassifierAuthor.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids))
        classifier_titles = list(MClassifierTitle.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids))
        classifier_tags = list(MClassifierTag.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids))
        classifier_texts = list(MClassifierText.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids))
        classifier_urls = list(MClassifierUrl.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids))
    else:
        classifier_feeds = []
        classifier_authors = []
        classifier_titles = []
        classifier_tags = []
        classifier_texts = []
        classifier_urls = []

    folder_feed_ids = None

    sort_classifiers_by_feed(
        user=user,
        feed_ids=found_feed_ids,
        classifier_feeds=classifier_feeds,
        classifier_authors=classifier_authors,
        classifier_titles=classifier_titles,
        classifier_tags=classifier_tags,
        classifier_texts=classifier_texts,
        classifier_urls=classifier_urls,
        folder_feed_ids=folder_feed_ids,
    )
    for story in stories:
        story["intelligence"] = {
            "feed": apply_classifier_feeds(classifier_feeds, story["story_feed_id"]),
            "author": apply_classifier_authors(classifier_authors, story, folder_feed_ids=folder_feed_ids),
            "tags": apply_classifier_tags(classifier_tags, story, folder_feed_ids=folder_feed_ids),
            "title": apply_classifier_titles(classifier_titles, story, folder_feed_ids=folder_feed_ids),
            "title_regex": 0,
            "text": 0,
            "text_regex": 0,
            "url": apply_classifier_urls(classifier_urls, story, folder_feed_ids=folder_feed_ids),
            "url_regex": 0,
        }
        story["score"] = UserSubscription.score_story(story["intelligence"])
        if unread_filter == "focus" and story["score"] >= 1:
            filtered_stories.append(story)
        elif unread_filter == "unread" and story["score"] >= 0:
            filtered_stories.append(story)

    stories = filtered_stories

    data = {}
    data["title"] = "%s from %s (%s sites)" % (folder_title, user.username, len(feed_ids))
    data["link"] = "https://%s%s" % (domain, reverse("folder", kwargs=dict(folder_name=folder_title)))
    data["description"] = "Unread stories in %s on NewsBlur. From %s's account and contains %s sites." % (
        folder_title,
        user.username,
        len(feed_ids),
    )
    data["lastBuildDate"] = datetime.datetime.utcnow()
    data["generator"] = "NewsBlur - %s" % settings.NEWSBLUR_URL
    data["docs"] = None
    data["author_name"] = user.username
    data["feed_url"] = "https://%s%s" % (
        domain,
        reverse(
            "folder-rss-feed",
            kwargs=dict(
                user_id=user_id,
                secret_token=secret_token,
                unread_filter=unread_filter,
                folder_slug=folder_slug,
            ),
        ),
    )
    rss = feedgenerator.Atom1Feed(**data)

    for story in stories:
        feed = Feed.get_by_id(story["story_feed_id"])
        feed_title = feed.feed_title if feed else ""
        try:
            usersub = UserSubscription.objects.get(user=user, feed=feed)
            if usersub.user_title:
                feed_title = usersub.user_title
        except UserSubscription.DoesNotExist:
            usersub = None

        story_content = """%s<br><br><img src="//%s/rss_feeds/icon/%s" width="16" height="16"> %s""" % (
            smart_str(story["story_content"]),
            Site.objects.get_current().domain,
            story["story_feed_id"],
            feed_title,
        )
        story_content = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", "", story_content)
        story_title = "%s%s" % (("%s: " % feed_title) if feed_title else "", story["story_title"])
        internal_story_url = "https://%s/site/%s/%s/" % (
            domain,
            story["story_feed_id"],
            story["guid_hash"],
        )
        story_data = {
            "title": story_title,
            "link": story["story_permalink"] or internal_story_url,
            "description": story_content,
            "categories": story["story_tags"],
            "unique_id": internal_story_url,
            "pubdate": localtime_for_timezone(story["story_date"], user.profile.timezone),
        }
        if story["story_authors"]:
            story_data["author_name"] = story["story_authors"]
        rss.add_item(**story_data)

    logging.user(
        request,
        "~FBGenerating ~SB%s~SN's folder RSS feed (%s, %s stories): ~FM%s"
        % (user.username, folder_title, len(stories), request.META.get("HTTP_USER_AGENT", "")[:24]),
    )

    # Cache the RSS response for 60 seconds
    rss_content = rss.writeString("utf-8")
    cache.set(cache_key, rss_content, 60)
    return HttpResponse(rss_content, content_type="application/rss+xml")
