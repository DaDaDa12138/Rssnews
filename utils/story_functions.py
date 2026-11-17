"""Story content processing: HTML sanitization, text diffing, date formatting, and hashing.

Core utilities for preparing story content for display -- strips unsafe HTML,
generates content diffs between story versions, formats relative dates, and
produces story content hashes for deduplication.
"""

import base64
import datetime
import hashlib
import hmac
import re
import sys
import urllib.parse
from itertools import chain
from random import randint

import dateutil
import feedparser
import lxml.etree
import lxml.html
from django.utils import formats, translation
from django.utils.dateformat import DateFormat
from django.utils.html import strip_tags as strip_tags_django
from django.utils.translation import gettext
from lxml.etree import ParserError, SerialisationError, XMLSyntaxError
from lxml.html.clean import Cleaner
from lxml.html.diff import fixup_ins_del_tags, htmldiff_tokens, tokenize

from utils.tornado_escape import linkify as linkify_tornado
from utils.tornado_escape import xhtml_unescape as xhtml_unescape_tornado

COMMENTS_RE = re.compile(r"<!--.*?-->")

_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_CDN_PROXY_HOSTS = {"i0.wp.com", "i1.wp.com", "i2.wp.com", "i3.wp.com"}
_SIZE_PREFIX_RE = re.compile(r"^[lsm]-")
_IMAGE_MEDIA_EXTENSIONS = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")


def _normalize_image_url_for_dedup(url):
    """Strip scheme, query params, fragments, www., and CDN proxy hosts to get a canonical host+path."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url.lower()

    # CDN services (Brightspot, etc.) embed source image URL in ?url= param
    if parsed.query:
        query_params = urllib.parse.parse_qs(parsed.query)
        source_url = query_params.get("url", [None])[0]
        if source_url:
            return _normalize_image_url_for_dedup(source_url)

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if host.startswith("www."):
        host = host[4:]

    # WordPress Photon CDN: i0.wp.com/example.com/path/image.jpg
    if host in _CDN_PROXY_HOSTS:
        inner = path.lstrip("/")
        if "/" in inner:
            host, path = inner.split("/", 1)[0].lower(), "/" + inner.split("/", 1)[1]
        else:
            host, path = inner.lower(), "/"
        if host.startswith("www."):
            host = host[4:]

    # Strip CMS image size prefixes from filename (e.g., l-intro-1234.jpg → intro-1234.jpg)
    if "/" in path:
        directory, filename = path.rsplit("/", 1)
        filename = _SIZE_PREFIX_RE.sub("", filename)
        path = directory + "/" + filename

    return host + path


def _image_url_matches_content(media_url, story_content):
    """Check if an image URL (or a variant with different scheme/params/CDN) already exists in content."""
    if not media_url or not story_content:
        return False
    if media_url in story_content:
        return True

    normalized_media = _normalize_image_url_for_dedup(media_url)
    if not normalized_media or len(normalized_media) < 8:
        return False

    for match in _IMG_SRC_RE.finditer(story_content):
        if _normalize_image_url_for_dedup(match.group(1)) == normalized_media:
            return True

    return False


def _media_url_looks_like_image(media_url):
    if not media_url:
        return False

    try:
        path = urllib.parse.urlparse(media_url).path
    except Exception:
        path = media_url

    return urllib.parse.unquote(path).lower().endswith(_IMAGE_MEDIA_EXTENSIONS)


def midnight_today(now=None):
    if not now:
        now = datetime.datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def midnight_yesterday(midnight=None):
    if not midnight:
        midnight = midnight_today()
    return midnight - datetime.timedelta(days=1)


def beginning_of_this_month():
    return datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def uses_english_dates():
    """utils/story_functions.py keeps NewsBlur's English date style; other languages use Django's locale formats."""
    return (translation.get_language() or "en").startswith("en")


def localized_date(date, english_format):
    if uses_english_dates():
        return date.strftime(english_format)
    return formats.date_format(date, "DATE_FORMAT", use_l10n=True)


def format_story_link_date__short(date, now=None):
    if not now:
        now = datetime.datetime.now()
    date = date.replace(tzinfo=None)
    midnight = midnight_today(now)
    english = uses_english_dates()
    time = (
        date.strftime("%I:%M%p").lstrip("0").lower() if english else formats.time_format(date, use_l10n=True)
    )
    if date >= midnight:
        return time
    elif date >= midnight_yesterday(midnight):
        return gettext("Yesterday, %(time)s") % {"time": time}
    if english:
        return "%s, %s" % (date.strftime("%d %b %Y"), time)
    day = formats.date_format(date, "SHORT_DATE_FORMAT", use_l10n=True)
    return gettext("%(date)s, %(time)s") % {"date": day, "time": time}


def format_story_link_date__long(date, now=None):
    if not now:
        now = datetime.datetime.now()
    date = date.replace(tzinfo=None)
    midnight = midnight_today(now)

    if uses_english_dates():
        parsed_date = DateFormat(date)
        if date >= midnight:
            return "Today, " + parsed_date.format("F jS ") + date.strftime("%I:%M%p").lstrip("0").lower()
        elif date >= midnight_yesterday(midnight):
            return "Yesterday, " + parsed_date.format("F jS g:ia").replace(".", "")
        elif date >= beginning_of_this_month():
            return parsed_date.format("l, F jS g:ia").replace(".", "")
        else:
            return parsed_date.format("l, F jS, Y g:ia").replace(".", "")

    # utils/story_functions.py uses the full DATE_FORMAT because some locales' month-day format
    # has the wrong grammatical case (Russian "2 Октябрь" instead of "2 октября").
    values = {
        "date": formats.date_format(date, "DATE_FORMAT", use_l10n=True),
        "time": formats.time_format(date, use_l10n=True),
        "weekday": formats.date_format(date, "l", use_l10n=True),
    }
    if date >= midnight:
        return gettext("Today, %(date)s %(time)s") % values
    elif date >= midnight_yesterday(midnight):
        return gettext("Yesterday, %(date)s %(time)s") % values
    return gettext("%(weekday)s, %(date)s %(time)s") % values


def extract_story_date(entry):
    published = entry.get("published")
    if isinstance(published, datetime.datetime):
        # Already extracted by an earlier pass over this entry (a retried archive page);
        # parsing it as a string would fail over to now and lose the real date.
        return published
    # Do not switch to published_parsed or every story will be dated the fetch time
    publish_date = entry.get("g_parsed") or entry.get("updated_parsed")
    if publish_date:
        try:
            publish_date = datetime.datetime(*publish_date[:6])
        except (ValueError, TypeError, OverflowError):
            # Garbage feed dates (year 0, month 13) can't build a datetime, so fall
            # through to the published string below and then to now().
            publish_date = None

    if not publish_date and entry.get("published"):
        try:
            # Feeds that only ship a date string still carry their own offset
            # ("+08:00", "Z"); story_date is stored as naive UTC, so convert first
            # instead of dropping the offset and keeping local wall-clock time.
            parsed = dateutil.parser.parse(entry.get("published"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(datetime.timezone.utc)
            publish_date = parsed.replace(tzinfo=None)
        except (ValueError, TypeError, OverflowError):
            pass

    if not publish_date:
        publish_date = datetime.datetime.now() + datetime.timedelta(seconds=randint(0, 59))

    if publish_date < datetime.datetime(2000, 1, 1):
        publish_date = datetime.datetime.now()

    # Future dated stories get forced to current date
    if publish_date > datetime.datetime.now():
        publish_date = datetime.datetime.now() + datetime.timedelta(seconds=randint(0, 59))

    return publish_date


EMBEDDABLE_IFRAME_DOMAINS = [
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "player.vimeo.com",
    "www.google.com",
    "w.soundcloud.com",
    "open.spotify.com",
    "bandcamp.com",
]


def strip_non_embeddable_iframes(content):
    """Strip iframes from story content whose domains block cross-origin embedding.

    Many sites (e.g. Slashdot) include iframes in their RSS feeds that set
    X-Frame-Options: SAMEORIGIN, causing them to render as empty boxes.
    Only keep iframes from domains known to allow cross-origin embedding.
    """
    if not content or "<iframe" not in content.lower():
        return content

    def replace_iframe(match):
        iframe_html = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', iframe_html)
        if not src_match:
            return ""
        src = src_match.group(1)
        try:
            domain = urllib.parse.urlparse(src).hostname or ""
        except Exception:
            return ""
        if any(domain == d or domain.endswith("." + d) for d in EMBEDDABLE_IFRAME_DOMAINS):
            return iframe_html
        return ""

    return re.sub(r"<iframe\b[^>]*>.*?</iframe>", replace_iframe, content, flags=re.IGNORECASE | re.DOTALL)


def pre_process_story(entry, encoding):
    entry["published"] = extract_story_date(entry)

    # entry_link = entry.get('link') or ''
    # protocol_index = entry_link.find("://")
    # if protocol_index != -1:
    #     entry['link'] = (entry_link[:protocol_index+3]
    #                     + urlquote(entry_link[protocol_index+3:]))
    # else:
    #     entry['link'] = urlquote(entry_link)
    if isinstance(entry.get("guid"), dict):
        entry["guid"] = str(entry["guid"])

    # Normalize story content/summary
    summary = entry.get("summary") or ""
    content = ""
    if not summary and "summary_detail" in entry:
        summary = entry["summary_detail"].get("value", "")
    if entry.get("content"):
        # Some feeds (e.g. Ghost-published 404media) emit a media:description
        # alongside content:encoded, which feedparser merges into entry.content.
        # Prefer text/html so we don't drop the real article body for a short
        # plain-text caption; fall back to the longest value if no html exists.
        html_items = [c for c in entry["content"] if c.get("type") == "text/html"]
        chosen = (
            max(html_items, key=lambda c: len(c.get("value", "") or ""))
            if html_items
            else max(entry["content"], key=lambda c: len(c.get("value", "") or ""))
        )
        content = chosen.get("value", "") or ""
    if len(content) > len(summary):
        entry["story_content"] = content.strip()
    else:
        entry["story_content"] = summary.strip()
    if not entry["story_content"] and entry.get("subtitle"):
        entry["story_content"] = entry.get("subtitle")

    if "summary_detail" in entry and entry["summary_detail"].get("type", None) == "text/plain":
        try:
            entry["story_content"] = feedparser.sanitizer._sanitize_html(
                entry["story_content"], encoding, "text/plain"
            )
            if encoding and not isinstance(entry["story_content"], str):
                entry["story_content"] = entry["story_content"].decode(encoding, "ignore")
        except UnicodeEncodeError:
            pass

    # Add each media enclosure as a Download link
    for media_content, is_media_content in chain(
        ((media, True) for media in entry.get("media_content", [])[:15]),
        ((link, False) for link in entry.get("links", [])[:15]),
    ):
        media_url = media_content.get("url", media_content.get("href", ""))
        media_type = media_content.get("type", media_content.get("medium", ""))
        if not media_type and is_media_content and _media_url_looks_like_image(media_url):
            media_type = "image"
        if media_url and media_type and media_url not in entry["story_content"]:
            media_type_name = media_type.split("/")[0]
            if "audio" in media_type and media_url:
                entry[
                    "story_content"
                ] += """<br><br>
                    <audio controls="controls" preload="none">
                        <source src="%(media_url)s" type="%(media_type)s" />
                    </audio>""" % {
                    "media_url": media_url,
                    "media_type": media_type,
                }
            elif "video" in media_type and media_url:
                entry[
                    "story_content"
                ] += """<br><br>
                    <video controls="controls" preload="none">
                        <source src="%(media_url)s" type="%(media_type)s" />
                    </video>""" % {
                    "media_url": media_url,
                    "media_type": media_type,
                }
            elif "image" in media_type and media_url:
                if not _image_url_matches_content(media_url, entry["story_content"]):
                    entry["story_content"] += """<br><br><img src="%s" />""" % media_url
                continue
            elif media_content.get("rel", "") == "alternative" or "text" in media_content.get("type", ""):
                continue
            elif media_type_name in ["application"]:
                continue
            entry[
                "story_content"
            ] += """<br><br>
                Download %(media_type)s: <a href="%(media_url)s">%(media_url)s</a>""" % {
                "media_type": media_type_name,
                "media_url": media_url,
            }

    entry["guid"] = entry.get("guid") or entry.get("id") or entry.get("link") or str(entry.get("published"))

    if not entry.get("title"):
        entry["title"] = ""

    entry["title"] = strip_tags(entry.get("title"))
    entry["author"] = strip_tags(entry.get("author"))
    if not entry["author"]:
        entry["author"] = strip_tags(entry.get("credit"))

    entry["story_content"] = attach_media_scripts(entry["story_content"])
    entry["story_content"] = fix_responsive_embeds(entry["story_content"])
    entry["story_content"] = strip_non_embeddable_iframes(entry["story_content"])

    return entry


def fix_responsive_embeds(content):
    """Fix responsive video embed pattern missing position styles.

    Many sites use a div with height:0 + padding-bottom to create a 16:9 aspect
    ratio container, with an iframe inside at width/height 100%. This requires
    position:relative on the wrapper and position:absolute on the iframe, but
    those styles often come from the site's CSS rather than inline styles. When
    rendered in the reader without the site's CSS, the iframe collapses to 0 height.
    """
    if not content or "<iframe" not in content.lower():
        return content

    def fix_wrapper(match):
        div_tag = match.group(1)
        inner = match.group(2)
        # Check if wrapper has height:0 and padding-bottom (responsive embed pattern)
        style_match = re.search(r'style=["\']([^"\']*)["\']', div_tag, re.IGNORECASE)
        if not style_match:
            return match.group(0)
        style = style_match.group(1)
        has_zero_height = re.search(r"height\s*:\s*0", style)
        has_padding_bottom = re.search(r"padding-bottom\s*:", style)
        if not has_zero_height or not has_padding_bottom:
            return match.group(0)
        # Add position:relative to wrapper if missing
        if "position" not in style.lower():
            new_style = style.rstrip("; ") + "; position: relative;"
            div_tag = div_tag.replace(style_match.group(1), new_style)

        # Add position:absolute to child iframes if missing
        def fix_iframe_position(iframe_match):
            iframe_html = iframe_match.group(0)
            iframe_style = re.search(r'style=["\']([^"\']*)["\']', iframe_html, re.IGNORECASE)
            if iframe_style and "position" not in iframe_style.group(1).lower():
                new_iframe_style = (
                    iframe_style.group(1).rstrip("; ") + "; position: absolute; top: 0; left: 0;"
                )
                iframe_html = iframe_html.replace(iframe_style.group(1), new_iframe_style)
            elif not iframe_style:
                iframe_html = iframe_html.replace(
                    "<iframe", '<iframe style="position: absolute; top: 0; left: 0;"', 1
                )
            return iframe_html

        inner = re.sub(
            r"<iframe\b[^>]*>.*?</iframe>", fix_iframe_position, inner, flags=re.IGNORECASE | re.DOTALL
        )
        return div_tag + inner + "</div>"

    return re.sub(r"(<div\b[^>]*>)(.*?)</div>", fix_wrapper, content, flags=re.IGNORECASE | re.DOTALL)


def restore_instagram_data_attributes(content):
    """Restore data-instgrm-permalink on Instagram embed blockquotes.

    feedparser's sanitizer strips data-* attributes, which removes the
    data-instgrm-permalink that Instagram's embeds.js needs to render the embed.
    This reconstructs it from the <a href> inside each blockquote.
    """
    if "instagram-media" not in content:
        return content

    def add_permalink(match):
        tag = match.group(0)
        if "data-instgrm-permalink" in tag:
            return tag
        blockquote_end = content.find("</blockquote>", match.start())
        if blockquote_end == -1:
            return tag
        block_content = content[match.start() : blockquote_end]
        href_match = re.search(r'href="(https://www\.instagram\.com/(?:reel|p)/[^"]+)"', block_content)
        if href_match:
            url = href_match.group(1)
            return tag.replace(
                'class="instagram-media"',
                f'class="instagram-media" data-instgrm-permalink="{url}" data-instgrm-version="14"',
            )
        return tag

    return re.sub(r'<blockquote[^>]*class="instagram-media"[^>]*>', add_permalink, content)


def attach_media_scripts(content):
    if "instagram-media" in content and "<script" not in content:
        content = restore_instagram_data_attributes(content)
        content += '<script async defer src="https://platform.instagram.com/en_US/embeds.js"></script><script>(function(){if(window.instgrm)window.instgrm.Embeds.process()})()</script>'
    if "twitter-tweet" in content and "<script" not in content:
        content += '<script id="twitter-wjs" type="text/javascript" async defer src="https://platform.twitter.com/widgets.js"></script>'
    if "imgur-embed-pub" in content and "<script" not in content:
        content += '<script async src="https://s.imgur.com/min/embed.js" charset="utf-8"></script>'
    return content


def strip_tags(html):
    if not html:
        return ""
    return strip_tags_django(html)


def strip_tags_preserve_blockquote(html):
    if not html:
        return ""
    # Extract blockquote, strip tags from the rest, then reassemble
    match = re.match(r"^<blockquote>(.*?)</blockquote>\s*(.*)", html, re.DOTALL)
    if match:
        quote_text = strip_tags_django(match.group(1))
        rest = strip_tags_django(match.group(2))
        result = "<blockquote>" + quote_text + "</blockquote>"
        if rest:
            result += "\n" + rest
        return result
    return strip_tags_django(html)


def strip_comments(html_string):
    return COMMENTS_RE.sub("", html_string)


def strip_comments__lxml(html_string=""):
    if not html_string:
        return html_string

    params = {
        "comments": True,
        "scripts": False,
        "javascript": False,
        "style": False,
        "links": False,
        "meta": False,
        "page_structure": False,
        "processing_instructions": False,
        "embedded": False,
        "frames": False,
        "forms": False,
        "annoying_tags": False,
        "remove_tags": None,
        "allow_tags": None,
        "remove_unknown_tags": True,
        "safe_attrs_only": False,
    }
    try:
        cleaner = Cleaner(**params)
        html = lxml.html.fromstring(html_string)
        clean_html = cleaner.clean_html(html)

        return lxml.etree.tostring(clean_html).decode()
    except (XMLSyntaxError, ParserError, SerialisationError):
        return html_string


def prep_for_search(html):
    html = strip_tags_django(html)
    html = html.lower()
    html = xhtml_unescape_tornado(html)

    return html[:100000]


def linkify(*args, **kwargs):
    return xhtml_unescape_tornado(linkify_tornado(*args, **kwargs))


def htmldiff(old_html, new_html):
    """Return new_html marked up with <ins>/<del> around whatever changed.

    This must never raise. lxml's diff keeps its delete ranges in the chunk list
    as DEL_START/DEL_END sentinels and resolves them in a cleanup pass, but that
    pass gives up on deletes that span unbalanced tags: diffing
    "<div>aaa bbb" against "<div><div><div>aaa" leaves a sentinel behind and the
    join below dies with "sequence item N: expected str instance, type found"
    (lxml 6.1.3). Because the caller stores the result as the story body, an
    exception here used to abort the whole story update in
    apps/rss_feeds/models.py. A missing diff is far cheaper than a lost update,
    so anything that cannot be diffed cleanly falls back to the new document,
    exactly like the parse failures this function already tolerated.
    """
    # NUL bytes are not valid in HTML and make lxml's parser complain.
    old_html = (old_html or "").replace("\x00", "")
    new_html = (new_html or "").replace("\x00", "")

    try:
        old_html_tokens = tokenize(old_html, include_hrefs=False)
        new_html_tokens = tokenize(new_html, include_hrefs=False)
        result = htmldiff_tokens(old_html_tokens, new_html_tokens)
        result = "".join(result).strip()
        return fixup_ins_del_tags(result)
    except (AttributeError, KeyError, ParserError, TypeError, ValueError):
        # AttributeError/TypeError: leftover DEL_START/DEL_END sentinels.
        # KeyError/ParserError: lxml could not parse the markup.
        # ValueError: a chunk lxml refuses to serialize.
        return new_html


def create_imageproxy_signed_url(base_url, hmac_key, url, options=None):
    """Create a imageproxy signed URL for the specified image URL
    Args:
        base_url: Base URL of the imageproxy installation
        hmac_key: HMAC shared key to be used for signing
        url: URL of the destination image
    Returns:
        str: A full url that can be used to serve the proxied image
    """
    if not options:
        options = []
    if isinstance(options, int):
        options = [str(options)]
    if not isinstance(options, list):
        options = [options]
    if sys.getdefaultencoding() == "ascii":
        url = url.encode("utf-8")

    if url.startswith("data:"):
        return url

    base_url = base_url.rstrip("/")
    signature = base64.urlsafe_b64encode(
        hmac.new(hmac_key.encode(), msg=url.encode(), digestmod=hashlib.sha256).digest()
    )
    options.append("sc")
    options.append("s" + signature.decode())

    return "{base}/{options}/{url}".format(base=base_url, options=",".join(options), url=url)
