import http.client
import re
import ssl
import time
import traceback
import urllib.error
import urllib.parse
import zlib
from socket import error as SocketError

import feedparser
import requests
from django.utils.encoding import smart_bytes
from utils.documents import NotUniqueError

from apps.rss_feeds.models import MFeedPage
from apps.rss_feeds.text_importer import is_blocked_response
from utils import log as logging
from utils.feed_functions import TimeoutError, timelimit
from utils.url_safety import UnsafeUrlError, safe_requests_get, validate_public_url

# from utils.feed_functions import mail_feed_error_to_admin

BROKEN_PAGES = [
    "tag:",
    "info:",
    "uuid:",
    "urn:",
    "[]",
]

# Also change in reader_utils.js.
BROKEN_PAGE_URLS = [
    "nytimes.com",
    "github.com",
    "washingtonpost.com",
    "stackoverflow.com",
    "stackexchange.com",
    "twitter.com",
    "rankexploits",
    "gamespot.com",
    "espn.com",
    "royalroad.com",
]


class PageImporter(object):
    def __init__(self, feed, story=None, request=None):
        self.feed = feed
        self.story = story
        self.request = request

    @property
    def headers(self):
        return {
            "User-Agent": "NewsBlur Page Fetcher - %s subscriber%s - %s %s"
            % (
                self.feed.num_subscribers,
                "s" if self.feed.num_subscribers != 1 else "",
                self.feed.permalink,
                self.feed.fake_user_agent,
            ),
        }

    def fetch_page(self, urllib_fallback=False, requests_exception=None):
        try:
            self.fetch_page_timeout(urllib_fallback=urllib_fallback, requests_exception=requests_exception)
        except TimeoutError:
            logging.user(
                self.request,
                "   ***> [%-30s] ~FBPage fetch ~SN~FRfailed~FB due to timeout" % (self.feed.log_title[:30]),
            )

    @timelimit(10)
    def fetch_page_timeout(self, urllib_fallback=False, requests_exception=None):
        html = None
        feed_link = self.feed.feed_link
        if not feed_link:
            self.save_no_page(reason="No feed link")
            return

        if feed_link.startswith("www"):
            self.feed.feed_link = "http://" + feed_link
        try:
            if any(feed_link.startswith(s) for s in BROKEN_PAGES):
                self.save_no_page(reason="Broken page")
                return
            elif any(s in feed_link.lower() for s in BROKEN_PAGE_URLS):
                self.save_no_page(reason="Banned")
                return
            elif feed_link.startswith("http"):
                if urllib_fallback:
                    response = safe_requests_get(feed_link, headers=self.headers, timeout=10)
                    time.sleep(0.01)  # Grrr, GIL.
                    data = self._decode_response(response)
                else:
                    try:
                        response = safe_requests_get(feed_link, headers=self.headers, timeout=10)
                        if getattr(response, "connection", None):
                            response.connection.close()
                    except requests.exceptions.TooManyRedirects:
                        response = safe_requests_get(feed_link, timeout=10)
                    except (
                        UnsafeUrlError,
                        AttributeError,
                        SocketError,
                        ssl.SSLError,
                        TypeError,
                        requests.adapters.ReadTimeout,
                    ) as e:
                        logging.debug(
                            "   ***> [%-30s] Page fetch failed using requests: %s"
                            % (self.feed.log_title[:30], e)
                        )
                        self.save_no_page(reason="Page fetch failed")
                        return
                    encoding = response.encoding
                    content = response.content

                    # When servers don't specify charset in Content-Type header, requests
                    # defaults to ISO-8859-1 per RFC 2616, but most modern sites use UTF-8.
                    # Check if the HTML declares UTF-8 charset and use that instead.
                    if encoding and encoding.lower() in ("iso-8859-1", "latin-1", "latin1"):
                        content_start = content[:1024].lower()
                        if (
                            content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
                            or b'charset="utf-8"' in content_start
                            or b"charset='utf-8'" in content_start
                            or b"charset=utf-8" in content_start
                        ):
                            encoding = "utf-8"

                    try:
                        data = content.decode(encoding or "utf-8")
                    except (UnicodeDecodeError, LookupError):
                        data = content.decode("utf-8", errors="replace")
            else:
                try:
                    data = open(feed_link, "r").read()
                except IOError:
                    self.feed.feed_link = "http://" + feed_link
                    self.fetch_page(urllib_fallback=True)
                    return
            if data:
                html = self.rewrite_page(data)
                if html:
                    self.save_page(html)
                else:
                    self.save_no_page(reason="No HTML found")
                    return
            else:
                self.save_no_page(reason="No data found")
                return
        except (
            ValueError,
            urllib.error.URLError,
            http.client.BadStatusLine,
            http.client.InvalidURL,
            requests.exceptions.ConnectionError,
            UnsafeUrlError,
        ) as e:
            logging.debug("   ***> [%-30s] Page fetch failed: %s" % (self.feed.log_title[:30], e))
            self.feed.save_page_history(401, "Bad URL", e)
            try:
                validate_public_url(self.feed.feed_address)
                fp = feedparser.parse(self.feed.feed_address)
            except (UnsafeUrlError, urllib.error.HTTPError, urllib.error.URLError):
                return html
            feed_link = fp.feed.get("link", "")
            self.feed.save()
        except http.client.IncompleteRead as e:
            logging.debug("   ***> [%-30s] Page fetch failed: %s" % (self.feed.log_title[:30], e))
            self.feed.save_page_history(500, "IncompleteRead", e)
        except (requests.exceptions.RequestException, requests.packages.urllib3.exceptions.HTTPError) as e:
            logging.debug(
                "   ***> [%-30s] Page fetch failed using requests: %s" % (self.feed.log_title[:30], e)
            )
            # mail_feed_error_to_admin(self.feed, e, local_vars=locals())
            return self.fetch_page(urllib_fallback=True, requests_exception=e)
        except Exception:
            logging.debug("[%d] ! -------------------------" % (self.feed.id,))
            tb = traceback.format_exc()
            logging.debug(tb)
            logging.debug("[%d] ! -------------------------" % (self.feed.id,))
            self.feed.save_page_history(500, "Error", tb)
            # mail_feed_error_to_admin(self.feed, e, local_vars=locals())
            if not urllib_fallback:
                self.fetch_page(urllib_fallback=True)
        else:
            self.feed.save_page_history(200, "OK")

        return html

    def fetch_story(self):
        html = None
        try:
            html = self._fetch_story()
        except TimeoutError:
            logging.user(self.request, "~SN~FRFailed~FY to fetch ~FGoriginal story~FY: timed out")
        except requests.exceptions.TooManyRedirects:
            logging.user(self.request, "~SN~FRFailed~FY to fetch ~FGoriginal story~FY: too many redirects")

        return html

    @timelimit(30)
    def _fetch_story(self):
        html = None
        story_permalink = self.story.story_permalink

        if not self.feed:
            return
        if any(story_permalink.startswith(s) for s in BROKEN_PAGES):
            return
        if any(s in story_permalink.lower() for s in BROKEN_PAGE_URLS):
            return
        if not story_permalink.startswith("http"):
            return

        try:
            response = safe_requests_get(story_permalink, headers=self.headers, timeout=10)
            if getattr(response, "connection", None):
                response.connection.close()
        except (
            UnsafeUrlError,
            AttributeError,
            SocketError,
            ssl.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.TooManyRedirects,
            requests.adapters.ReadTimeout,
        ):
            try:
                response = safe_requests_get(story_permalink, timeout=10)
            except (
                UnsafeUrlError,
                AttributeError,
                SocketError,
                ssl.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.TooManyRedirects,
                requests.adapters.ReadTimeout,
            ) as e:
                logging.debug(
                    "   ***> [%-30s] Original story fetch failed using requests: %s"
                    % (self.feed.log_title[:30], e)
                )
                return

        if self._is_blocked_response(response):
            logging.user(
                self.request,
                "~SN~FYOriginal story ~FRblocked~FY (%s), no page to save: %s"
                % (response.status_code, story_permalink),
            )
            return
        else:
            data = self._decode_response(response)

        if data:
            data = data.replace("\xc2\xa0", " ")  # Non-breaking space, is mangled when encoding is not utf-8
            data = data.replace("\\u00a0", " ")  # Non-breaking space, is mangled when encoding is not utf-8
            html = self.rewrite_page(data)
            if not html:
                return
            self.save_story(html)

        return html

    def _decode_response(self, response):
        encoding = response.encoding
        content = response.content

        # When servers don't specify charset in Content-Type header, requests
        # defaults to ISO-8859-1 per RFC 2616, but most modern sites use UTF-8.
        # Check if the HTML declares UTF-8 charset and use that instead.
        if encoding and encoding.lower() in ("iso-8859-1", "latin-1", "latin1"):
            content_start = content[:1024].lower()
            if (
                content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
                or b'charset="utf-8"' in content_start
                or b"charset='utf-8'" in content_start
                or b"charset=utf-8" in content_start
            ):
                encoding = "utf-8"

        try:
            return content.decode(encoding or "utf-8")
        except (UnicodeDecodeError, LookupError):
            return content.decode("utf-8", errors="replace")

    def _is_blocked_response(self, response):
        """Check if a response indicates the request was blocked by anti-bot protection.
        The statuses and challenge markers live in apps/rss_feeds/text_importer.py so
        Story view and Text view agree on what a block looks like."""
        return is_blocked_response(response)

    def save_story(self, html):
        self.story.original_page_z = zlib.compress(smart_bytes(html))
        try:
            self.story.save()
        except NotUniqueError:
            pass

    def save_no_page(self, reason=None):
        logging.debug(
            "   ---> [%-30s] ~FYNo original page: %s / %s"
            % (self.feed.log_title[:30], reason, self.feed.feed_link)
        )
        self.feed.has_page = False
        self.feed.save()
        self.feed.save_page_history(404, f"Feed has no original page: {reason}")

    def rewrite_page(self, response):
        BASE_RE = re.compile(r"<head(.*?)>", re.I)
        base_code = '<base href="%s" />' % (self.feed.feed_link,)

        html = BASE_RE.sub("<head\1> " + base_code, response)

        if "<base href" not in html:
            html = "%s %s" % (base_code, html)

        # html = self.fix_urls(html)

        return html.strip()

    def fix_urls(self, document):
        # BEWARE: This will rewrite URLs inside of <script> tags. You know, like
        # Google Analytics. Ugh.

        FIND_RE = re.compile(r'\b(href|src)\s*=\s*("[^"]*"|\'[^\']*\'|[^"\'<>=\s]+)')
        ret = []
        last_end = 0

        for match in FIND_RE.finditer(document):
            url = match.group(2)
            if url[0] in "\"'":
                url = url.strip(url[0])
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == parsed.netloc == "":  # relative to domain
                url = urllib.parse.urljoin(self.feed.feed_link, url)
                ret.append(document[last_end : match.start(2)])
                ret.append('"%s"' % (url,))
                last_end = match.end(2)
        ret.append(document[last_end:])

        return "".join(ret)

    def save_page(self, html):
        if not html or len(html) < 100:
            return

        try:
            feed_page = MFeedPage.objects.get(feed_id=self.feed.pk)
            # feed_page.page_data = html.encode('utf-8')
            if feed_page.page() == html:
                logging.debug(
                    "   ---> [%-30s] ~FYNo change in page data: %s"
                    % (self.feed.log_title[:30], self.feed.feed_link)
                )
            else:
                feed_page.page_data = zlib.compress(smart_bytes(html))
                feed_page.save()
        except MFeedPage.DoesNotExist:
            feed_page = MFeedPage.objects.create(
                feed_id=self.feed.pk, page_data=zlib.compress(smart_bytes(html))
            )
        return feed_page
