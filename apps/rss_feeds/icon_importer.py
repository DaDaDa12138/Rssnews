import base64
import http.client
import operator
import ssl
import struct
import urllib.error
import urllib.parse
from io import BytesIO
from socket import error as SocketError

import lxml.html
import requests
from PIL import BmpImagePlugin, Image, PngImagePlugin
from requests.packages.urllib3.exceptions import LocationParseError

from apps.rss_feeds.models import MFeedIcon, MFeedPage
from utils import log as logging
from utils.feed_functions import TimeoutError, timelimit
from utils.url_safety import UnsafeUrlError, safe_requests_get


class IconImporter(object):
    def __init__(self, feed, page_data=None, force=False, declared_icon_url=None, declared_logo_url=None):
        self.feed = feed
        self.force = force
        self.page_data = page_data
        # The feed's self-declared images, captured from the source XML in
        # utils/feed_fetcher.py: Atom <icon> (preferred) and <logo> (fallback).
        self.declared_icon_url = declared_icon_url
        self.declared_logo_url = declared_logo_url
        self.feed_icon = MFeedIcon.get_feed(feed_id=self.feed.pk)
        if not self.feed_icon:
            # MFeedIcon.save() swallows the duplicate key error that two fetchers
            # racing on the same feed hit, so get_feed can hand back None. Carry on
            # with an unsaved icon instead of crashing on every attribute below.
            self.feed_icon = MFeedIcon(feed_id=self.feed.pk)

    def save(self):
        # Honor a freshly-declared <icon> even for feeds that already have a cached
        # icon or are marked favicon-not-found (e.g. an existing feed stuck on the
        # wrong site favicon, forum #13719). We only bypass the cache short-circuits
        # when the declared <icon> differs from both the cached icon and the last
        # declared URL we attempted -- declared_source_url is recorded after every
        # attempt so a broken or undecodable declared icon is not refetched each poll.
        declared_pending = bool(
            self.declared_icon_url
            and self.declared_icon_url != self.feed_icon.icon_url
            and self.declared_icon_url != self.feed_icon.declared_source_url
        )

        if not self.force and not declared_pending and self.feed.favicon_not_found:
            # print 'Not found, skipping...'
            return
        if (
            not self.force
            and not declared_pending
            and not self.feed.favicon_not_found
            and self.feed_icon.icon_url
        ):
            # YouTube feeds should only refetch while they still point at the
            # generic YouTube favicon. Real channel avatars and playlist art
            # should be treated as valid cached icons.
            if "youtube.com" not in self.feed.feed_address:
                return
            if not self.is_generic_youtube_icon(self.feed_icon.icon_url):
                return
        # Honor the feed's self-declared <icon>/<logo> before deriving a
        # favicon from the site's HTML or /favicon.ico.
        image, image_file, icon_url = self.fetch_declared_image()
        if not image:
            image, image_file, icon_url = self.fetch_image_from_page_data()
        if not image:
            image, image_file, icon_url = self.fetch_image_from_path(force=self.force)

        if not image:
            self.feed_icon.not_found = True
            # Remember the declared <icon> we just failed to fetch so the bypass
            # above doesn't retry it on every poll.
            if self.declared_icon_url:
                self.feed_icon.declared_source_url = self.declared_icon_url
            self.feed_icon.save()
            self.feed.favicon_not_found = True
            self.feed.save()
            return False

        image = self.normalize_image(image)
        try:
            color = self.determine_dominant_color_in_image(image)
        except (IndexError, ValueError, MemoryError, IOError, struct.error):
            # convert() forces PIL to finish decoding, so a corrupt or truncated
            # favicon only blows up here, not at fetch time.
            logging.debug("   ---> [%-30s] ~SN~FRFailed to measure icon" % self.feed.log_title[:30])
            return
        try:
            image_str = self.string_from_image(image)
        except TypeError:
            return

        if len(image_str) > 500000:
            image = None
        if image and (
            self.force
            or self.feed_icon.data != image_str
            or self.feed_icon.icon_url != icon_url
            or self.feed_icon.not_found
            or (self.declared_icon_url and self.feed_icon.declared_source_url != self.declared_icon_url)
        ):
            logging.debug(
                "   ---> [%-30s] ~SN~FBIcon difference:~FY color:%s (%s/%s) data:%s url:%s notfound:%s"
                % (
                    self.feed.log_title[:30],
                    self.feed_icon.color != color,
                    self.feed_icon.color,
                    color,
                    self.feed_icon.data != image_str,
                    self.feed_icon.icon_url != icon_url,
                    self.feed_icon.not_found,
                )
            )
            self.feed_icon.data = image_str
            self.feed_icon.icon_url = icon_url
            self.feed_icon.color = color
            self.feed_icon.not_found = False
            # Record the declared <icon> we resolved/attempted so the cache-bypass
            # above terminates once this declared URL has been handled.
            if self.declared_icon_url:
                self.feed_icon.declared_source_url = self.declared_icon_url
            self.feed_icon.save()
        if self.feed.favicon_color != color:
            self.feed.favicon_color = color
            self.feed.favicon_not_found = False
            self.feed.save(update_fields=["favicon_color", "favicon_not_found"])

        return not self.feed.favicon_not_found

    def is_generic_youtube_icon(self, icon_url):
        if not icon_url:
            return True

        generic_markers = (
            "youtube.com/favicon.ico",
            "youtube.com/s/desktop/",
            "youtube.com/s/desktop",
        )
        return any(marker in icon_url for marker in generic_markers)

    def load_icon(self, image_file, index=None):
        """
        DEPRECATED

        Load Windows ICO image.

        See http://en.wikipedia.org/w/index.php?oldid=264332061 for file format
        description.

        Cribbed and modified from http://djangosnippets.org/snippets/1287/
        """
        try:
            image_file.seek(0)
            header = struct.unpack("<3H", image_file.read(6))
        except Exception:
            return

        # Check magic
        if header[:2] != (0, 1):
            return

        # Collect icon directories
        directories = []
        for i in range(header[2]):
            directory = list(struct.unpack("<4B2H2I", image_file.read(16)))
            for j in range(3):
                if not directory[j]:
                    directory[j] = 256

            directories.append(directory)

        if index is None:
            # Select best icon
            directory = max(directories, key=operator.itemgetter(slice(0, 3)))
        else:
            directory = directories[index]

        # Seek to the bitmap data
        image_file.seek(directory[7])

        prefix = image_file.read(16)
        image_file.seek(-16, 1)

        if PngImagePlugin._accept(prefix):
            # Windows Vista icon with PNG inside
            try:
                image = PngImagePlugin.PngImageFile(image_file)
            except IOError:
                return
        else:
            # Load XOR bitmap
            try:
                image = BmpImagePlugin.DibImageFile(image_file)
            except IOError:
                return
            if image.mode == "RGBA":
                # Windows XP 32-bit color depth icon without AND bitmap
                pass
            else:
                # Patch up the bitmap height
                image.size = image.size[0], image.size[1] >> 1
                d, e, o, a = image.tile[0]
                image.tile[0] = d, (0, 0) + image.size, o, a

                # Calculate AND bitmap dimensions. See
                # http://en.wikipedia.org/w/index.php?oldid=264236948#Pixel_storage
                # for description
                offset = o + a[1] * image.size[1]
                stride = ((image.size[0] + 31) >> 5) << 2
                size = stride * image.size[1]

                # Load AND bitmap
                image_file.seek(offset)
                string = image_file.read(size)
                mask = Image.frombytes("1", image.size, string, "raw", ("1;I", stride, -1))

                image = image.convert("RGBA")
                image.putalpha(mask)

        return image

    def fetch_declared_image(self):
        # apps/rss_feeds/icon_importer.py: honor the feed's self-declared images,
        # captured from the source XML in utils/feed_fetcher.py. The Atom <icon> is a
        # square favicon-style image and is preferred; <logo> is a larger banner used
        # only as a fallback (and may be an SVG that PIL can't decode, in which case we
        # fall through to the site-derived favicon).
        for url in (self.declared_icon_url, self.declared_logo_url):
            if not url:
                continue
            image, image_file = self.get_image_from_url(url)
            if image:
                return image, image_file, url
        return None, None, None

    def fetch_image_from_page_data(self):
        image = None
        image_file = None
        content = None
        if self.page_data:
            content = self.page_data
        else:
            content = MFeedPage.get_data(feed_id=self.feed.pk)
        url = self._url_from_html(content)
        if not url:
            try:
                headers = {
                    "User-Agent": "NewsBlur Favicon Fetcher - %s subscriber%s - %s %s"
                    % (
                        self.feed.num_subscribers,
                        "s" if self.feed.num_subscribers != 1 else "",
                        self.feed.permalink,
                        self.feed.fake_user_agent,
                    ),
                }
                content = safe_requests_get(self.cleaned_feed_link, headers=headers, timeout=10).content
                url = self._url_from_html(content)
            except (
                UnsafeUrlError,
                AttributeError,
                SocketError,
                requests.ConnectionError,
                requests.models.MissingSchema,
                requests.sessions.InvalidSchema,
                requests.sessions.TooManyRedirects,
                requests.models.InvalidURL,
                requests.models.ChunkedEncodingError,
                requests.models.ContentDecodingError,
                http.client.IncompleteRead,
                requests.adapters.ReadTimeout,
                LocationParseError,
                ssl.SSLError,
                ValueError,
            ) as e:
                logging.debug(" ---> ~SN~FRFailed~FY to fetch ~FGfeed icon~FY: %s" % e)
        if url:
            image, image_file = self.get_image_from_url(url)
        return image, image_file, url

    @property
    def cleaned_feed_link(self):
        if self.feed.feed_link.startswith("http"):
            return self.feed.feed_link
        return "http://" + self.feed.feed_link

    def fetch_image_from_path(self, path="favicon.ico", force=False):
        image = None
        url = None

        if not force:
            url = self.feed_icon.icon_url
        if not url and self.feed.feed_link and len(self.feed.feed_link) > 6:
            try:
                url = urllib.parse.urljoin(self.feed.feed_link, "favicon.ico")
            except ValueError:
                url = None
        if not url:
            return None, None, None

        image, image_file = self.get_image_from_url(url)
        if not image:
            url = urllib.parse.urljoin(self.feed.feed_link, "/favicon.ico")
            image, image_file = self.get_image_from_url(url)
        # print 'Found: %s - %s' % (url, image)
        return image, image_file, url

    def get_image_from_url(self, url):
        # print 'Requesting: %s' % url
        if not url:
            return None, None

        @timelimit(30)
        def _1(url):
            headers = {
                "User-Agent": "NewsBlur Favicon Fetcher - %s subscriber%s - %s %s"
                % (
                    self.feed.num_subscribers,
                    "s" if self.feed.num_subscribers != 1 else "",
                    self.feed.permalink,
                    self.feed.fake_user_agent,
                ),
                "Connection": "close",
                "Accept": "image/png,image/x-icon,image/*;q=0.9,*/*;q=0.8",
            }
            try:
                icon = safe_requests_get(url, headers=headers, timeout=30).content
            except (UnsafeUrlError, requests.RequestException):
                return None
            return icon

        try:
            icon = _1(url)
        except TimeoutError:
            return None, None

        try:
            icon_file = BytesIO(icon)
            image = Image.open(icon_file)
        except (IOError, ValueError):
            return None, None

        return image, icon_file

    def _url_from_html(self, content):
        url = None
        if not content:
            return url
        try:
            if isinstance(content, str):
                content = content.encode("utf-8")
            icon_path = lxml.html.fromstring(content).xpath(
                '//link[@rel="icon" or @rel="shortcut icon"]/@href'
            )
        except (lxml.etree.ParserError, TypeError):
            return url

        if icon_path:
            if str(icon_path[0]).startswith("http"):
                url = icon_path[0]
            else:
                url = urllib.parse.urljoin(self.feed.feed_link, icon_path[0])
        return url

    def normalize_image(self, image):
        # if image.size != (16, 16):
        #     image = image.resize((16, 16), Image.BICUBIC)
        if image.mode != "RGBA":
            try:
                image = image.convert("RGBA")
            except IOError:
                pass

        return image

    def determine_dominant_color_in_image(self, image):
        # Quantize the icon to a small palette and take the most common color that is
        # neither near black nor near white, so the color stays readable on both the
        # light and dark themes.
        quantized = image.convert("RGB").quantize(colors=8, method=Image.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts = sorted(quantized.getcolors() or [], reverse=True)
        if not counts:
            return self.feed.adjust_color("808080", 21)

        for count, index in counts:
            red, green, blue = palette[index * 3 : index * 3 + 3]
            if (red < 60 and green < 60 and blue < 60) or (red > 200 and green > 200 and blue > 200):
                continue
            color = "{:02x}{:02x}{:02x}".format(red, green, blue)
            return self.feed.adjust_color(color[:6], 21)

        count, index = counts[0]
        red, green, blue = palette[index * 3 : index * 3 + 3]
        color = "{:02x}{:02x}{:02x}".format(red, green, blue)
        return self.feed.adjust_color(color[:6], 21)

    def string_from_image(self, image):
        output = BytesIO()
        image.save(output, "png", quality=95)
        contents = output.getvalue()
        output.close()
        return base64.b64encode(contents).decode()
