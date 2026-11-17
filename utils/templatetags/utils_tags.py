import datetime
import glob
import os
import re
import struct

from django import template
from django.conf import settings
from django.contrib.sites.models import Site
from django.utils import dateformat, formats, translation
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from pipeline.templatetags.pipeline import JavascriptNode, StylesheetNode

from utils import log as logging
from utils.story_functions import localized_date, uses_english_dates
from utils.user_functions import get_user
from vendor.timezones.utilities import localtime_for_timezone

register = template.Library()


@register.simple_tag
def current_domain(dev=False, strip_www=False):
    current_site = Site.objects.get_current()
    domain = current_site and current_site.domain
    if dev and settings.SERVER_NAME in ["dev"] and domain:
        domain = domain.replace("www", "dev")
    if strip_www:
        domain = domain.replace("www.", "")
    return domain


@register.simple_tag(takes_context=True)
def localdatetime(context, date, date_format):
    user = get_user(context["user"])
    date = localtime_for_timezone(date, user.profile.timezone).strftime(date_format)
    return date


@register.simple_tag(takes_context=True)
def localdate(context, date, english_format):
    """utils_tags.py shows a calendar date in the viewer's timezone and language."""
    user = get_user(context["user"])
    return localized_date(localtime_for_timezone(date, user.profile.timezone), english_format)


@register.simple_tag
def bidi(left_to_right, right_to_left):
    """utils_tags.py picks a style value by the active language's direction, so emails mirror their layout for
    Arabic and Hebrew readers: float: {% bidi "left" "right" %}."""
    return right_to_left if translation.get_language_bidi() else left_to_right


@register.filter
def language_date(date, english_format):
    """utils_tags.py writes a date in NewsBlur's English style (a Django date format like "F j, Y") for English
    readers and in the active language's own DATE_FORMAT otherwise, as in emails sent in their reader's language.
    """
    if not date:
        return ""
    if uses_english_dates():
        return dateformat.format(date, english_format)
    return formats.date_format(date, "DATE_FORMAT", use_l10n=True)


@register.inclusion_tag("reader/feeds_skeleton.xhtml", takes_context=True)
def render_feeds_skeleton(context):
    user = get_user(context["user"])

    return {
        "user": user,
        "user_profile": user.profile,
        "MEDIA_URL": settings.MEDIA_URL,
        "account_images": list(range(1, 4)),
    }


@register.inclusion_tag("reader/dashboard_rivers.xhtml", takes_context=True)
def render_dashboard_rivers_left(context, dashboard_rivers):
    user = get_user(context["user"])

    return {"user": user, "dashboard_rivers": dashboard_rivers, "side": "left"}


@register.inclusion_tag("reader/dashboard_rivers.xhtml", takes_context=True)
def render_dashboard_rivers_right(context, dashboard_rivers):
    user = get_user(context["user"])

    return {"user": user, "dashboard_rivers": dashboard_rivers, "side": "right"}


@register.inclusion_tag("reader/dashboard_river.xhtml", takes_context=True)
def render_dashboard_river(context, dashboard_river):
    user = get_user(context["user"])

    return {
        "user": user,
        "dashboard_river": dashboard_river,
    }


@register.inclusion_tag("reader/manage_module.xhtml", takes_context=True)
def render_manage_module(context):
    user = get_user(context["user"])

    return {
        "user": user,
        "user_profile": user.profile,
    }


@register.inclusion_tag("reader/footer.xhtml", takes_context=True)
def render_footer(context, page=None, show_language=True):
    return {
        "page": page,
        "show_language": show_language,
        "MEDIA_URL": settings.MEDIA_URL,
        "request": context.get("request"),
        "user": context.get("user"),
        # utils_tags.py hands every language_context value to the footer's language selector.
        **{key: value for key, value in context.flatten().items() if key.startswith("ui_")},
    }


@register.filter
def get(h, key):
    print(h, key)
    return h[key]


@register.filter
def hex2rgba(hex, alpha):
    colors = struct.unpack("BBB", hex.decode("hex"))
    return "rgba(%s, %s, %s, %s)" % (colors[0], colors[1], colors[2], alpha)


@register.filter
def rgb2rgba(rgb, alpha):
    rgb = rgb.replace("rgb", "rgba")
    rgb = rgb.replace(")", ", %s)" % alpha)
    return rgb


@register.filter
def color2rgba(color, alpha):
    if "#" in color:
        return hex2rgba(color, alpha)
    elif "rgb" in color:
        return rgb2rgba(color, alpha)


@register.filter
def get_range(value):
    """
    Filter - returns a list containing range made from given value
    Usage (in template):

    <ul>{% for i in 3|get_range %}
      <li>{{ i }}. Do something</li>
    {% endfor %}</ul>

    Results with the HTML:
    <ul>
      <li>0. Do something</li>
      <li>1. Do something</li>
      <li>2. Do something</li>
    </ul>

    Instead of 3 one may use the variable set in the views
    """
    return list(range(value))


@register.filter
def commify(n):
    """
    Add commas to an integer n.
    >>> commify(1)
    '1'
    >>> commify(123)
    '123'
    >>> commify(1234)
    '1,234'
    >>> commify(1234567890)
    '1,234,567,890'
    >>> commify(123.0)
    '123.0'
    >>> commify(1234.5)
    '1,234.5'
    >>> commify(1234.56789)
    '1,234.56789'
    >>> commify('%.2f' % 1234.5)
    '1,234.50'
    >>> commify(None)

    """
    if n is None:
        return None
    if not uses_english_dates():
        # utils_tags.py groups digits like the active language; English keeps its original commas.
        return formats.number_format(n, use_l10n=True, force_grouping=True)
    n = str(n)
    if "." in n:
        dollars, cents = n.split(".")
    else:
        dollars, cents = n, None

    r = []
    for i, c in enumerate(reversed(dollars)):
        if i and (not (i % 3)):
            r.insert(0, ",")
        r.insert(0, c)
    out = "".join(r)
    if cents:
        out += "." + cents
    return out


@register.simple_tag
def settings_value(name):
    # Django 5 no longer coerces a non-string simple_tag result while rendering, and the
    # templates/base.html Globals block embeds these values inside a JS object literal, so
    # always hand back a string (DAYS_OF_UNREAD is an int).
    return str(getattr(settings, name, ""))


@register.filter
def smooth_timedelta(timedeltaobj):
    """Convert a datetime.timedelta object into Days, Hours, Minutes, Seconds."""
    if isinstance(timedeltaobj, datetime.datetime):
        # utils_tags.py compares against the naive UTC stamps stored on Feed (see
        # Feed.update_last_update), so use utcnow() instead of now(): the result must not
        # depend on the container's TZ.
        timedeltaobj = timedeltaobj - datetime.datetime.utcnow()
    secs = timedeltaobj.total_seconds()
    overdue = secs < 0
    secs = abs(secs)
    timetot = ""
    if not overdue:
        timetot += "in "

    if secs > 86400:  # 60sec * 60min * 24hrs
        days = secs // 86400
        timetot += "{} days".format(int(days))
        secs = secs - days * 86400

    if secs > 3600:
        hrs = secs // 3600
        timetot += " {} hours".format(int(hrs))
        secs = secs - hrs * 3600

    if secs > 60:
        mins = secs // 60
        timetot += " {} min".format(int(mins))
        secs = secs - mins * 60

    if secs > 0:
        timetot += " {} sec".format(int(secs))

    if overdue:
        timetot += " ago"

    return timetot


def _bundle_version(asset_type, name):
    """utils_tags.py: stamps every bundle URL with the newest source file mtime.

    media/js and media/css are edited in place and were served with a seven day cache
    before Round 4, so a browser that cached them back then keeps the stale file without
    ever asking the server. A version query turns each edit into a new URL, which any
    normal reload fetches.
    """
    try:
        filenames = settings.PIPELINE[asset_type][name]["source_filenames"]
    except (AttributeError, KeyError, TypeError):
        return None
    newest = 0
    for filename in filenames:
        # assets.yml: bundle entries are relative to media/ and may be globs (css/controls/*.css)
        matches = glob.glob(os.path.join(settings.MEDIA_ROOT, filename))
        if not matches:
            matches = [os.path.join(settings.NEWSBLUR_DIR, filename)]
        for path in matches:
            try:
                newest = max(newest, int(os.path.getmtime(path)))
            except OSError:
                continue
    return newest or None


def _resolved_bundle_name(node, context):
    """utils_tags.py: token.split_contents() keeps the quotes, so the bundle name is
    a template variable exactly as Pipeline resolves it ("common" -> common)."""
    try:
        return template.Variable(node.name).resolve(context)
    except Exception:
        return node.name


def _version_asset_urls(html, asset_type, name):
    """utils_tags.py: appends ?v=<newest mtime> to each script/link URL in the bundle."""
    version = _bundle_version(asset_type, name)
    if not version:
        return html
    versioned = re.sub(r'(src|href)="(/[^"?]+\.(?:js|css))"', r'\1="\2?v=%d"' % version, html)
    return mark_safe(versioned)


def _script_nonce(context):
    """utils_tags.py: the per-response CSP nonce, or "" outside a request."""
    request = context.get("request") if context else None
    return getattr(request, "csp_nonce", "") if request else ""


def _add_script_nonce(html, context):
    """utils_tags.py: every bundle script carries the response nonce so the
    report-only strict CSP sees a clean page without editing each template."""
    nonce = _script_nonce(context)
    if not nonce:
        return html
    return mark_safe(re.sub(r"<script(?=[\s>])", '<script nonce="%s"' % nonce, html))


class DebugAssetsAwareJavascriptNode(JavascriptNode):
    """JavascriptNode that respects DEBUG_ASSETS instead of DEBUG."""

    def render(self, context):
        # Temporarily override DEBUG setting for Pipeline to respect DEBUG_ASSETS
        original_debug = settings.DEBUG
        try:
            if hasattr(settings, "DEBUG_ASSETS"):
                settings.DEBUG = settings.DEBUG_ASSETS
            output = super().render(context)
        finally:
            settings.DEBUG = original_debug
        output = _version_asset_urls(output, "JAVASCRIPT", _resolved_bundle_name(self, context))
        return _add_script_nonce(output, context)


@register.tag
def include_javascripts(parser, token):
    """Prints out a template of <script> tags based on an asset package name."""
    tag_name, name = token.split_contents()
    return DebugAssetsAwareJavascriptNode(name)
    # asset_type = 'javascripts'
    # return mark_safe(settings.JAMMIT.render_tags(asset_type, asset_package))


class RawJSNode(JavascriptNode):
    def render(self, context):
        output = super(RawJSNode, self).render(context)
        paths = re.findall(r"src=\"/(.*?)\"", output, re.MULTILINE)
        assert paths
        output = ""
        for filename in paths:
            abs_filename = os.path.join(settings.NEWSBLUR_DIR, filename)
            f = open(abs_filename, "r")
            output += f.read()
        return output


@register.tag
def include_javascripts_raw(parser, token):
    """Prints out the JS code found in the static asset packages."""
    tag_name, name = token.split_contents()
    scripts = RawJSNode(name)
    return scripts


class RawStylesheetNode(StylesheetNode):
    def render(self, context):
        output = super(RawStylesheetNode, self).render(context)
        paths = re.findall(r"href=\"/(.*?)\"", output, re.MULTILINE)
        assert paths
        output = ""
        for filename in paths:
            abs_filename = os.path.join(settings.NEWSBLUR_DIR, filename)
            f = open(abs_filename, "r")
            output += f.read().replace('"', '\\"').replace("\n", "")
        return output


@register.tag
def include_stylesheets_raw(parser, token):
    """Prints out the CSS code found in the static asset packages."""
    tag_name, name = token.split_contents()
    scripts = RawStylesheetNode(name)
    return scripts


class DebugAssetsAwareStylesheetNode(StylesheetNode):
    """StylesheetNode that respects DEBUG_ASSETS instead of DEBUG, and links mirrored CSS on RTL pages."""

    def render(self, context):
        # utils_tags.py: a right-to-left page links the mirrored copy of "common" or "blurblog"
        # (utils/rtl_css.py, served by apps/profile/language.py) instead of the LTR bundle, so every
        # template that includes one, including pages that include "common" twice, stays mirrored.
        flipped_stylesheets = context.get("ui_flipped_stylesheets")
        if flipped_stylesheets:
            flipped_url = flipped_stylesheets.get(template.Variable(self.name).resolve(context))
            if flipped_url:
                return format_html(
                    '<link href="{}" rel="stylesheet" type="text/css" media="all" />', flipped_url
                )
        # Temporarily override DEBUG setting for Pipeline to respect DEBUG_ASSETS
        original_debug = settings.DEBUG
        try:
            if hasattr(settings, "DEBUG_ASSETS"):
                settings.DEBUG = settings.DEBUG_ASSETS
            output = super().render(context)
        except ValueError as error:
            # utils_tags.py keeps right-to-left pages up when code ships before its static build:
            # the hand-written rtl overrides are optional, the mirrored common sheet still loads.
            if template.Variable(self.name).resolve(context) != "rtl":
                raise
            logging.error(" ***> Missing the rtl stylesheet bundle, run deploy_static: %s" % error)
            return ""
        finally:
            settings.DEBUG = original_debug
        return _version_asset_urls(output, "STYLESHEETS", _resolved_bundle_name(self, context))


@register.tag
def include_stylesheets(parser, token):
    """Prints out a template of <link> tags based on an asset package name."""
    tag_name, name = token.split_contents()
    return DebugAssetsAwareStylesheetNode(name)
    # asset_type = 'stylesheets'
    # return mark_safe(settings.JAMMIT.render_tags(asset_type, asset_package))
