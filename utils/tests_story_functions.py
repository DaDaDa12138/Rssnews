"""Tests for the HTML diff used to mark up updated stories.

utils/tests_story_functions.py

apps/rss_feeds/models.py stores the output of htmldiff() as the story body, so
the function has to survive whatever markup a feed throws at it. lxml's diff
leaves its DEL_START/DEL_END sentinels behind when a delete spans unbalanced
tags, and the join that follows then dies with "sequence item N: expected str
instance, type found", which used to abort the entire story update.
"""

from django.test import SimpleTestCase

from utils.story_functions import htmldiff


class Test_Htmldiff(SimpleTestCase):
    def test_balanced_change_marks_both_sides(self):
        diff = htmldiff("<p>one two three</p>", "<p>one four three</p>")

        self.assertIn("<ins>four</ins>", diff)
        self.assertIn("<del>two</del>", diff)

    def test_identical_documents_are_returned_unchanged(self):
        self.assertEqual(htmldiff("<p>same</p>", "<p>same</p>"), "<p>same</p>")

    def test_delete_spanning_unbalanced_tags_falls_back_to_new_html(self):
        # lxml 6.1.3 leaves a DEL_START sentinel in the chunk list for this pair.
        old_html = "<div>aaa bbb"
        new_html = "<div><div><div>aaa"

        self.assertEqual(htmldiff(old_html, new_html), new_html)
        self.assertEqual(htmldiff("<div><div>aaa bbb", new_html), new_html)

    def test_nul_bytes_never_reach_the_result(self):
        diff = htmldiff("<p>a\x00b</p>", "<p>a\x00c</p>")

        self.assertNotIn("\x00", diff)
        self.assertIsInstance(diff, str)

    def test_missing_documents_do_not_raise(self):
        self.assertIsInstance(htmldiff(None, "<p>hi</p>"), str)
        self.assertEqual(htmldiff("", ""), "")

    def test_tricky_markup_always_returns_a_string(self):
        pairs = [
            ("<table><tr><td>a</td></tr></table>", "<table><tr><td>b</td></tr>"),
            ("<ul><li>a<li>b</ul>", "<ul><li>a</ul>"),
            ("<p>a</p></div></div>", "<p>b</p>"),
            ("<blockquote><p>x</p></blockquote>", "<p>x</p>"),
            ("<div>\x00</div>", "<div>y</div>"),
        ]

        for old_html, new_html in pairs:
            with self.subTest(old=old_html, new=new_html):
                diff = htmldiff(old_html, new_html)
                self.assertIsInstance(diff, str)
                self.assertNotIn("DEL_START", diff)
                self.assertNotIn("DEL_END", diff)
