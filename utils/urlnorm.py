"""
URI Normalization function:
 * Always provide the URI scheme in lowercase characters.
 * Always provide the host, if any, in lowercase characters.
 * Only perform percent-encoding where it is essential.
 * Always use uppercase A-through-F characters when percent-encoding.
 * Prevent dot-segments appearing in non-relative URI paths.
 * For schemes that define a default authority, use an empty authority if the
   default is desired.
 * For schemes that define an empty path to be equivalent to a path of "/",
   use "/".
 * For schemes that define a port, use an empty port if the default is desired
 * All portions of the URI must be utf-8 encoded NFC from Unicode strings

implements:
  http://gbiv.com/protocols/uri/rev-2002/rfc2396bis.html#canonical-form
  http://www.intertwingly.net/wiki/pie/PaceCanonicalIds

inspired by:
  Tony J. Ibbs,    http://starship.python.net/crew/tibs/python/tji_url.py
  Mark Nottingham, http://www.mnot.net/python/urlnorm.py
"""

__license__ = "Python"


from url_normalize import url_normalize

default_port = {
    "ftp": 21,
    "telnet": 23,
    "http": 80,
    "gopher": 70,
    "news": 119,
    "nntp": 119,
    "prospero": 191,
    "https": 443,
    "snews": 563,
    "snntp": 563,
}


def normalize(url):
    try:
        return url_normalize(url)
    except (UnicodeError, ValueError) as e:
        # UnicodeError: malformed URLs with invalid domain labels (empty or >63 chars)
        # ValueError: URLs with empty/invalid IP addresses (e.g., from malformed OPML imports)
        import logging

        logging.debug(f" ---> ~FRFailed to normalize URL: {e} - URL: {url}")
        return url if url else None


if __name__ == "__main__":
    import unittest

    suite = unittest.TestSuite()

    """ from http://www.intertwingly.net/wiki/pie/PaceCanonicalIds """
    tests = [
        (False, "http://:@example.com/"),
        (False, "http://@example.com/"),
        (False, "http://example.com"),
        (False, "HTTP://example.com/"),
        (False, "http://EXAMPLE.COM/"),
        (False, "http://example.com/%7Ejane"),
        (False, "http://example.com/?q=%C7"),
        (False, "http://example.com/?q=%5c"),
        (False, "http://example.com/?q=C%CC%A7"),
        (False, "http://example.com/a/../a/b"),
        (False, "http://example.com/a/./b"),
        (False, "http://example.com:80/"),
        (True, "http://example.com/"),
        (True, "http://example.com/?q=%C3%87"),
        (True, "http://example.com/?q=%E2%85%A0"),
        (True, "http://example.com/?q=%5C"),
        (True, "http://example.com/~jane"),
        (True, "http://example.com/a/b"),
        (True, "http://example.com:8080/"),
        (True, "http://user:password@example.com/"),
        # from rfc2396bis
        (True, "ftp://ftp.is.co.za/rfc/rfc1808.txt"),
        (True, "http://www.ietf.org/rfc/rfc2396.txt"),
        (True, "ldap://[2001:db8::7]/c=GB?objectClass?one"),
        (True, "mailto:John.Doe@example.com"),
        (True, "news:comp.infosystems.www.servers.unix"),
        (True, "tel:+1-816-555-1212"),
        (True, "telnet://192.0.2.16:80/"),
        (True, "urn:oasis:names:specification:docbook:dtd:xml:4.1.2"),
        # other
        (True, "http://127.0.0.1/"),
        (False, "http://127.0.0.1:80/"),
        (True, "http://www.w3.org/2000/01/rdf-schema#"),
        (False, "http://example.com:081/"),
    ]

    def testcase(expected, value):
        class test(unittest.TestCase):
            def runTest(self):
                assert (normalize(value) == value) == expected, (expected, value, normalize(value))

        return test()

    for expected, value in tests:
        suite.addTest(testcase(expected, value))

    """ mnot test suite; three tests updated for rfc2396bis. """
    tests = {
        "/foo/bar/.": "/foo/bar/",
        "/foo/bar/./": "/foo/bar/",
        "/foo/bar/..": "/foo/",
        "/foo/bar/../": "/foo/",
        "/foo/bar/../baz": "/foo/baz",
        "/foo/bar/../..": "/",
        "/foo/bar/../../": "/",
        "/foo/bar/../../baz": "/baz",
        "/foo/bar/../../../baz": "/baz",  # was: '/../baz',
        "/foo/bar/../../../../baz": "/baz",
        "/./foo": "/foo",
        "/../foo": "/foo",  # was: '/../foo',
        "/foo.": "/foo.",
        "/.foo": "/.foo",
        "/foo..": "/foo..",
        "/..foo": "/..foo",
        "/./../foo": "/foo",  # was: '/../foo',
        "/./foo/.": "/foo/",
        "/foo/./bar": "/foo/bar",
        "/foo/../bar": "/bar",
        "/foo//": "/foo/",
        "/foo///bar//": "/foo/bar/",
        "http://www.foo.com:80/foo": "http://www.foo.com/foo",
        "http://www.foo.com:8000/foo": "http://www.foo.com:8000/foo",
        "http://www.foo.com./foo/bar.html": "http://www.foo.com/foo/bar.html",
        "http://www.foo.com.:81/foo": "http://www.foo.com:81/foo",
        "http://www.foo.com/%7ebar": "http://www.foo.com/~bar",
        "http://www.foo.com/%7Ebar": "http://www.foo.com/~bar",
        "ftp://user:pass@ftp.foo.net/foo/bar": "ftp://user:pass@ftp.foo.net/foo/bar",
        "http://USER:pass@www.Example.COM/foo/bar": "http://USER:pass@www.example.com/foo/bar",
        "http://www.example.com./": "http://www.example.com/",
        "-": "-",
    }

    def testcase(original, normalized):
        class test(unittest.TestCase):
            def runTest(self):
                assert normalize(original) == normalized, (original, normalized, normalize(original))

        return test()

    for original, normalized in list(tests.items()):
        suite.addTest(testcase(original, normalized))

    """ execute tests """
    unittest.TextTestRunner().run(suite)
