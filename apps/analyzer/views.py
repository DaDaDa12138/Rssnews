"""Intelligence trainer views: save and retrieve per-user classifiers for story scoring.

Handles saving classifier rules (by title, author, tag, feed) and populating the
trainer modal with current classifier state.
"""

import redis
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext
from django.views.decorators.http import require_POST
from utils.documents import NotUniqueError

from apps.analyzer.models import (
    MClassifierAuthor,
    MClassifierFeed,
    MClassifierTag,
    MClassifierText,
    MClassifierTitle,
    MClassifierUrl,
    get_classifiers_for_user,
    validate_regex_pattern,
)
from apps.reader.models import UserSubscription
from apps.rss_feeds.models import Feed
from utils import json_functions as json
from utils import log as logging
from utils.user_functions import ajax_login_required, get_user


def index(request):
    # /classifier/ has no page of its own, the trainer lives inside the reader.
    return redirect("index")


@require_POST
@ajax_login_required
@json.json_view
def save_classifier(request):
    post = request.POST
    feed_id = post.get("feed_id")
    if not feed_id:
        return dict(code=-1, message=gettext("Missing feed_id"))
    feed = None
    social_user_id = None

    # Scope controls: 'feed' (default), 'folder', or 'global'
    scope = post.get("scope", "feed")

    # Feed ids arrive as either a numeric feed id or a 'social:<user id>' blurblog id,
    # so reject anything else instead of blowing up on int().
    if feed_id.startswith("social:"):
        try:
            social_user_id = int(feed_id.replace("social:", ""))
        except ValueError:
            return dict(code=-1, message="Invalid feed_id: %s" % feed_id)
        feed_id = None
    else:
        try:
            feed_id = int(feed_id)
        except ValueError:
            return dict(code=-1, message="Invalid feed_id: %s" % feed_id)
        if feed_id:
            feed = get_object_or_404(Feed, pk=feed_id)
    code = 0
    message = "OK"
    payload = {}
    scope_folder_name = post.get("folder_name", "")
    if scope not in ("feed", "folder", "global"):
        scope = "feed"

    # Folder and global scopes were an Archive feature; the personal edition
    # keeps every classifier on a single site.
    if scope != "feed":
        scope = "feed"

    logging.user(
        request,
        "~FGSaving classifier: ~SB%s~SN (scope=%s%s) ~FW%s"
        % (feed, scope, " folder=%s" % scope_folder_name if scope == "folder" else "", post),
    )

    # Mark subscription as dirty, so unread counts can be recalculated
    usersub = None
    if scope == "feed":
        try:
            usersub = UserSubscription.objects.get(user=request.user, feed=feed)
        except UserSubscription.DoesNotExist:
            pass
        if usersub and (not usersub.needs_unread_recalc or not usersub.is_trained):
            usersub.needs_unread_recalc = True
            usersub.is_trained = True
            usersub.save()
    elif scope == "global":
        # Mark all user subscriptions as needing recalc
        UserSubscription.objects.filter(user=request.user).update(needs_unread_recalc=True)
    elif scope == "folder":
        # Mark subscriptions in the folder as needing recalc
        from apps.reader.models import UserSubscriptionFolders

        try:
            usf = UserSubscriptionFolders.objects.get(user=request.user)
            flat_folders = usf.flatten_folders()
            folder_feed_ids = flat_folders.get(scope_folder_name, [])
            if folder_feed_ids:
                UserSubscription.objects.filter(user=request.user, feed_id__in=folder_feed_ids).update(
                    needs_unread_recalc=True
                )
        except UserSubscriptionFolders.DoesNotExist:
            pass

    def _save_classifier(ClassifierCls, content_type):
        # Standard classifiers (non-regex)
        classifiers = {
            "like_" + content_type: (1, False),
            "dislike_" + content_type: (-1, False),
            "super_dislike_" + content_type: (-2, False),
            "remove_like_" + content_type: (0, False),
            "remove_dislike_" + content_type: (0, False),
            "remove_super_dislike_" + content_type: (0, False),
        }
        # Add regex classifier for title, text, url, and author types
        if content_type in ("title", "text", "url", "author"):
            classifiers.update(
                {
                    "like_" + content_type + "_regex": (1, True),
                    "dislike_" + content_type + "_regex": (-1, True),
                    "super_dislike_" + content_type + "_regex": (-2, True),
                    "remove_like_" + content_type + "_regex": (0, True),
                    "remove_dislike_" + content_type + "_regex": (0, True),
                    "remove_super_dislike_" + content_type + "_regex": (0, True),
                }
            )

        # Determine scope fields for this classifier type (not applicable to feed classifier)
        use_scope = content_type != "feed" and scope != "feed"

        for opinion, (score, is_regex) in classifiers.items():
            if opinion in post:
                post_contents = post.getlist(opinion)
                for post_content in post_contents:
                    if not post_content:
                        continue

                    # Validate regex patterns before saving
                    if is_regex and score != 0:
                        is_valid, error_msg = validate_regex_pattern(post_content)
                        if not is_valid:
                            logging.user(
                                request, "~FRInvalid regex pattern: %s - %s" % (post_content, error_msg)
                            )
                            continue

                    classifier_dict = {
                        "user_id": request.user.pk,
                        "feed_id": 0 if use_scope else (feed_id or 0),
                        "social_user_id": social_user_id or 0,
                    }
                    if use_scope:
                        classifier_dict["scope"] = scope
                        classifier_dict["folder_name"] = scope_folder_name if scope == "folder" else ""
                    if content_type in ("author", "tag", "title", "text", "url"):
                        max_length = ClassifierCls._meta.get_field(content_type).max_length
                        classifier_dict.update({content_type: post_content[:max_length]})
                        # Add is_regex for title, text, url, and author classifiers
                        if content_type in ("title", "text", "url", "author"):
                            classifier_dict["is_regex"] = is_regex
                    elif content_type == "feed":
                        if not post_content.startswith("social:"):
                            classifier_dict["feed_id"] = post_content
                    try:
                        classifier = ClassifierCls.objects.get(**classifier_dict)
                    except ClassifierCls.DoesNotExist:
                        # Fallback for old classifiers missing scope/is_regex/folder_name fields
                        fallback_dict = {
                            k: v
                            for k, v in classifier_dict.items()
                            if k not in ("scope", "folder_name", "is_regex")
                        }
                        if fallback_dict != classifier_dict:
                            try:
                                classifier = ClassifierCls.objects.get(**fallback_dict)
                            except (ClassifierCls.DoesNotExist, ClassifierCls.MultipleObjectsReturned):
                                classifier = None
                        else:
                            classifier = None
                    except ClassifierCls.MultipleObjectsReturned:
                        classifiers_found = ClassifierCls.objects.filter(**classifier_dict)
                        if score == 0:
                            for classifier in classifiers_found:
                                classifier.delete()
                        else:
                            first_classifier = classifiers_found[0]
                            first_classifier.score = score
                            first_classifier.save()
                            for dup in classifiers_found[1:]:
                                dup.delete()
                        continue
                    if not classifier:
                        if score != 0:
                            try:
                                classifier_dict.update(dict(score=score))
                                classifier = ClassifierCls.objects.create(**classifier_dict)
                            except NotUniqueError:
                                continue
                    elif score == 0:
                        classifier.delete()
                    elif classifier.score != score:
                        classifier.score = score
                        classifier.save()

    _save_classifier(MClassifierAuthor, "author")
    _save_classifier(MClassifierTag, "tag")
    _save_classifier(MClassifierTitle, "title")
    _save_classifier(MClassifierText, "text")
    _save_classifier(MClassifierUrl, "url")
    _save_classifier(MClassifierFeed, "feed")

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "feed:%s" % feed_id)

    response = dict(code=code, message=message, payload=payload)
    return response


def get_classifiers_feed(request, feed_id):
    user = get_user(request)
    code = 0

    payload = get_classifiers_for_user(user, feed_id=feed_id)

    response = dict(code=code, payload=payload)

    return response


@require_POST
@ajax_login_required
@json.json_view
def save_all_classifiers(request):
    """
    Bulk save classifiers for multiple feeds in a single request.
    Expects JSON body with format:
    {
        "classifiers": {
            "feed_id": {
                "like_author": ["author1", "author2"],
                "dislike_tag": ["tag1"],
                "remove_like_title": ["title1"],
                ...
            },
            ...
        }
    }
    """
    try:
        body = json.decode(request.body)
    except (ValueError, TypeError):
        return {"code": -1, "message": gettext("Invalid JSON")}

    classifiers_by_feed = body.get("classifiers", {})
    if not classifiers_by_feed:
        return {"code": 0, "message": gettext("No classifiers to save")}

    logging.user(request, "~FGBulk saving classifiers for ~SB%s~SN feeds" % len(classifiers_by_feed))

    feeds_updated = []

    for feed_id_str, classifier_data in classifiers_by_feed.items():
        feed_id = None
        social_user_id = None

        if feed_id_str.startswith("social:"):
            social_user_id = int(feed_id_str.replace("social:", ""))
        else:
            feed_id = int(feed_id_str)

        # Mark subscription as dirty for unread recalc
        if social_user_id:
            pass
        else:
            try:
                usersub = UserSubscription.objects.get(user=request.user, feed_id=feed_id)
                if not usersub.needs_unread_recalc or not usersub.is_trained:
                    usersub.needs_unread_recalc = True
                    usersub.is_trained = True
                    usersub.save()
            except UserSubscription.DoesNotExist:
                pass

        # Process each classifier type
        _save_classifiers_for_feed(request.user.pk, feed_id, social_user_id, classifier_data)
        feeds_updated.append(feed_id_str)

    # Publish update notification
    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "feed:%s" % ",".join(map(str, feeds_updated)))

    return {"code": 0, "message": "OK", "feeds_updated": feeds_updated}


def _save_classifiers_for_feed(user_id, feed_id, social_user_id, classifier_data):
    """
    Helper function to save classifiers for a single feed.
    classifier_data is a dict like:
    {
        "like_author": ["author1"],
        "dislike_tag": ["tag1"],
        "like_title_regex": ["pattern.*"],
        ...
    }
    """
    classifier_types = {
        "author": MClassifierAuthor,
        "tag": MClassifierTag,
        "title": MClassifierTitle,
        "text": MClassifierText,
        "url": MClassifierUrl,
        "feed": MClassifierFeed,
    }

    # Types that support regex matching
    regex_types = ("title", "text", "url", "author")

    classifiers_config = {
        "like_": 1,
        "dislike_": -1,
        "remove_like_": 0,
        "remove_dislike_": 0,
    }

    for content_type, ClassifierCls in classifier_types.items():
        for prefix, score in classifiers_config.items():
            # Build list of keys to check: standard and regex (for applicable types)
            keys_to_check = [(prefix + content_type, False)]
            if content_type in regex_types:
                keys_to_check.append((prefix + content_type + "_regex", True))

            for key, is_regex in keys_to_check:
                if key not in classifier_data:
                    continue

                values = classifier_data[key]
                if not isinstance(values, list):
                    values = [values]

                for value in values:
                    if not value:
                        continue

                    # Validate regex patterns before saving
                    if is_regex and score != 0:
                        is_valid, error_msg = validate_regex_pattern(value)
                        if not is_valid:
                            logging.info("Invalid regex pattern: %s - %s" % (value, error_msg))
                            continue

                    classifier_dict = {
                        "user_id": user_id,
                        "feed_id": feed_id or 0,
                        "social_user_id": social_user_id or 0,
                    }

                    if content_type in ("author", "tag", "title", "text", "url"):
                        max_length = ClassifierCls._meta.get_field(content_type).max_length
                        classifier_dict[content_type] = value[:max_length]
                        # Set is_regex for types that support it
                        if content_type in regex_types:
                            classifier_dict["is_regex"] = is_regex
                    elif content_type == "feed":
                        if not str(value).startswith("social:"):
                            try:
                                classifier_dict["feed_id"] = int(value)
                            except (ValueError, TypeError):
                                # Skip invalid feed IDs
                                continue

                    try:
                        classifier = ClassifierCls.objects.get(**classifier_dict)
                    except ClassifierCls.DoesNotExist:
                        # Fallback for old classifiers missing scope/is_regex/folder_name fields
                        fallback_dict = {
                            k: v
                            for k, v in classifier_dict.items()
                            if k not in ("scope", "folder_name", "is_regex")
                        }
                        if fallback_dict != classifier_dict:
                            try:
                                classifier = ClassifierCls.objects.get(**fallback_dict)
                            except (ClassifierCls.DoesNotExist, ClassifierCls.MultipleObjectsReturned):
                                classifier = None
                        else:
                            classifier = None
                    except ClassifierCls.MultipleObjectsReturned:
                        classifiers = ClassifierCls.objects.filter(**classifier_dict)
                        if score == 0:
                            for classifier in classifiers:
                                classifier.delete()
                        else:
                            first_classifier = classifiers[0]
                            first_classifier.score = score
                            first_classifier.save()
                            for dup in classifiers[1:]:
                                dup.delete()
                        continue

                    if not classifier:
                        if score != 0:
                            try:
                                classifier_dict["score"] = score
                                ClassifierCls.objects.create(**classifier_dict)
                            except NotUniqueError:
                                pass
                    elif score == 0:
                        classifier.delete()
                    elif classifier.score != score:
                        classifier.score = score
                        classifier.save()
