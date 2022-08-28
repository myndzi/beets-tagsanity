import unittest
from beetsplug import tagsanity
from beets import config
from beets.autotag import TrackInfo, AlbumInfo
from tests.helper import TestHelper


class TagsanityPluginTest(unittest.TestCase, TestHelper):
    # fmt: off
    simple_replacements = {
        "simplify_curly_quotes": [
            ("\u00ab", "\""),  # « - left unicode "initial punctuation", class Pi
            ("\u201c", "\""),  # “ - left double curly quote
            ("\u201d", "\""),  # ” - right double curly quote
            ("\u00bb", "\""),  # » - right unicode "final punctuation", class Pf
            ("\u2018", "\'"),  # ‘ - left single curly quote
            ("\u2019", "\'"),  # ’ - right single curly quote
        ],
        "simplify_whitespace": [ # keep this in the middle so it doesn't get .strip()'d
            ("\u1680", " "),   #   - arbitrary unicode space, class Z
        ],
        "simplify_hyphens": [
            ("\u2e1a", "-"),   # ⸚ - arbitrary unicode hyphen, class Pd
        ],
        "simplify_brackets": [
            ("\uff08", "("),   # （ - fullwidth left parenthesis
            ("\uff09", ")"),   # ） - fullwidth right parenthesis
        ]
    }
    # fmt: on

    test_han = "\u660e"

    canonicalization_test = "\u0061\u0315\u0300\u05AE\u0300\u0062"
    #     "\u0061\u0315\u0300\u05AE\u0300\u0062",  # unicode canonicalization order test
    #     # NFC: 00E0 05AE 0300 0315 0062
    #     # NFD: 0061 05AE 0300 0300 0315 0062
    #     # NFKC: 00E0 05AE 0300 0315 0062
    #     # NFKD: 0061 05AE 0300 0300 0315 0062
    #     # (a◌̕◌̀◌֮◌̀b; à◌֮◌̀◌̕b; a◌֮◌̀◌̀◌̕b; à◌֮◌̀◌̕b; a◌֮◌̀◌̀◌̕b; )
    #     # LATIN SMALL LETTER A, COMBINING COMMA ABOVE RIGHT, COMBINING GRAVE ACCENT, HEBREW ACCENT ZINOR, COMBINING GRAVE ACCENT, LATIN SMALL LETTER B
    # }

    def setUp(self):
        self.setup_beets()
        self.plugin = tagsanity.TagSanity()
        self.load_plugins([self.plugin])

    def tearDown(self):
        self.teardown_beets()

    def _setup_config(self, **kwargs):
        config["tagsanity"] = {k: v for k, v in kwargs.items()}

        self.plugin.setup()

    def test_noop(self):
        """Ensure no changes are made to albums/tracks when everything is disabled."""
        self._setup_config(
            langs_enabled=[],
            tidy_unihandecode=False,
            drop_feats_from_fields=[],
            simplify_whitespace=False,
            simplify_hyphens=False,
            simplify_curly_quotes=False,
            simplify_brackets=False,
            unicode_normalization_mode=None,
        )

        chars = [self.test_han, self.canonicalization_test]
        for replacements in self.simple_replacements.values():
            for orig, _ in replacements:
                chars += orig

        text = "".join(chars)
        actual = self.plugin._process_string(None, text)
        self.assertEqual(actual, text)

    def test_strip(self):
        """Ensure strings are stripped"""
        self._setup_config(
            langs_enabled=[],
            tidy_unihandecode=False,
            drop_feats_from_fields=[],
            simplify_whitespace=False,
            simplify_hyphens=False,
            simplify_curly_quotes=False,
            simplify_brackets=False,
            unicode_normalization_mode=None,
        )

        text = " hi "
        self.assertEqual(self.plugin._process_string(None, text), "hi")

    def test_simple_replacements(self):
        """Verify that simple replacements work"""

        chars = []
        for replacements in self.simple_replacements.values():
            for orig, _ in replacements:
                chars += orig

        text = "".join(chars)

        for setting, replacements in self.simple_replacements.items():
            self.tearDown()
            self.setUp()
            plugin_config = {
                "langs_enabled": [],
                "tidy_unihandecode": False,
                "drop_feats_from_fields": [],
                "simplify_whitespace": False,
                "simplify_hyphens": False,
                "simplify_curly_quotes": False,
                "simplify_brackets": False,
                "unicode_normalization_mode": None,
            }
            plugin_config[setting] = True
            self._setup_config(**plugin_config)

            expect = text
            for orig, replacement in replacements:
                expect = expect.replace(orig, replacement)

            actual = self.plugin._process_string(None, text)

            self.assertEqual(actual, expect)

    def test_unicode_normalization(self):
        """Verify that unicode output is normalized when configured"""

        # fmt: off
        tests = [
            (None,   self.canonicalization_test, "\u0061\u0315\u0300\u05ae\u0300\u0062"),
            ("NFC",  self.canonicalization_test, "\u00e0\u05ae\u0300\u0315\u0062"),
            ("NFD",  self.canonicalization_test, "\u0061\u05ae\u0300\u0300\u0315\u0062"),
            ("NFKC", self.canonicalization_test, "\u00e0\u05ae\u0300\u0315\u0062"),
            ("NFKD", self.canonicalization_test, "\u0061\u05ae\u0300\u0300\u0315\u0062"),
            ("NFC",  "\ufffe",                   "") # \p{C} cleanup
        ]
        # fmt: on

        for pref, text, expect in tests:
            self.tearDown()
            self.setUp()
            self._setup_config(
                unicode_normalization_mode=pref,
            )

            actual = self.plugin._process_string(None, text)

            self.assertEqual(actual, expect)

    def test_han_preference(self):
        """Verify the han_preference setting is respected"""

        tests = [
            ("ja", "Mei"),
            ("kr", "Myeng"),
            ("vn", "Minh"),
            ("zh", "Ming"),
        ]

        for pref, expect in tests:
            self.tearDown()
            self.setUp()
            self._setup_config(
                langs_enabled=tagsanity.AVAILABLE_LANG_CODES,
                tidy_unihandecode=False,
                drop_feats_from_fields=[],
                simplify_whitespace=False,
                simplify_hyphens=False,
                simplify_curly_quotes=False,
                simplify_brackets=False,
                unicode_normalization_mode=None,
                han_preference=pref,
            )

            decoder = self.plugin._get_decoder(None, "Hani")
            actual = self.plugin._process_string(decoder, self.test_han)

            self.assertEqual(actual, expect)

    def test_bracket_preference(self):
        """Verify the bracket settings are respected"""

        self._setup_config(
            langs_enabled=[],
            tidy_unihandecode=False,
            drop_feats_from_fields=[],
            simplify_whitespace=False,
            simplify_hyphens=False,
            simplify_curly_quotes=False,
            simplify_brackets=True,
            left_bracket=">",
            right_bracket="<",
            unicode_normalization_mode=None,
        )

        expect = ">foo<"
        actual = self.plugin._process_string(None, "（foo）")

        self.assertEqual(actual, expect)

    def test_han_decodings(self):
        """Verify lang/script config, mapping, decoding"""

        # fmt: off
        tests = [
            ("jp", None,   "ja", "Mei"),
            ("jp", "Jpan", "ja", "Mei"),
            (None, "Jpan", "ja", "Mei"),
            ("ko", None,   "kr", "Myeng"),
            ("ko", "Kore", "kr", "Myeng"),
            (None, "Kore", "kr", "Myeng"),
            ("vi", None,   "vn", "Minh"),
            ("zh", None,   "zh", "Ming"),
            ("zh", "Hant", "zh", "Ming"),
            (None, "Hant", "zh", "Ming"),
        ]
        # fmt: on

        for lang, script, mapped, expected in tests:
            lang_opts = [[mapped], []]
            for enabled in lang_opts:
                self.tearDown()
                self.setUp()
                self._setup_config(
                    langs_enabled=enabled,
                    tidy_unihandecode=False,
                    drop_feats_from_fields=[],
                    simplify_whitespace=False,
                    simplify_hyphens=False,
                    simplify_curly_quotes=False,
                    simplify_brackets=False,
                    unicode_normalization_mode=None,
                )

                decoder = self.plugin._get_decoder(lang, script)
                actual = self.plugin._process_string(decoder, self.test_han)
                expect = expected if enabled else self.test_han

                self.assertEqual(actual, expect)

    def test_han_tidy(self):
        """Verify tidy_unihandecode does its job"""

        # Unihandecoder tends to leave trailing spaces, and concatenate
        # things together unexpectedly. It seems to just always add a
        # trailing space to a transliterated character, except (for
        # instance) things like Hiragana, which get concatenated against
        # the trailing transliteration. This appears to just be an error;
        # I don't yet know of any cases where this behavior is desirable.

        # fmt: off
        tests = [
            ('共鳴（空虚な石）',   False, 'Kyou Mei (Kuu Kyo naShaku )'),
            ('共鳴（空虚な石）',   True,  'Kyou Mei (Kuu Kyo na Shaku)'),
            # test a non-bracket option
            ('岩井俊二, 小林武史', False, 'Gan Sei Shun Ni , Shou Rin Bu Shi'),
            ('岩井俊二, 小林武史', True,  'Gan Sei Shun Ni, Shou Rin Bu Shi'),
            # is there any case for some text like "title 'with single quotes'" ?
            # if so, this option will need more work...
        ]
        # fmt: on

        for text, enabled, expect in tests:
            self.tearDown()
            self.setUp()
            self._setup_config(
                langs_enabled=tagsanity.AVAILABLE_LANG_CODES,
                tidy_unihandecode=enabled,
                drop_feats_from_fields=[],
                simplify_whitespace=False,
                simplify_hyphens=False,
                simplify_curly_quotes=False,
                simplify_brackets=False,
                unicode_normalization_mode=None,
            )

            decoder = self.plugin._get_decoder("jpn", "Jpan")
            actual = self.plugin._process_string(decoder, text)

            self.assertEqual(actual, expect)

    def test_process_object(self):
        """Verify that _process_object behaves correctly"""

        unicode_val = "\u2e1a"

        class Data(object):
            def __init__(self):
                self.foo = unicode_val

        tests = [
            ("foo", {"foo": "-"}),
            ("bar", {"foo": unicode_val}),
        ]

        for field, expect in tests:
            self.tearDown()
            self.setUp()
            self._setup_config(
                simplify_hyphens=True,
                process_fields=[field],
            )

            obj = Data()
            self.plugin._process_object(None, obj)
            actual = vars(obj)

            self.assertEqual(actual, expect)

    def test_album_hook(self):
        self._setup_config(
            han_preference="zh",
            process_fields=["title", "album"],
        )

        track = TrackInfo(track_id="mocktrack", title="title" + self.test_han, index=0)
        album = AlbumInfo(
            album_id="mockrelease",
            album="album" + self.test_han,
            tracks=[track],
            script="Jpan",
            language="jpn",
        )
        self.plugin._albuminfo_received(album)

        self.assertEqual("title Mei", track.title)
        self.assertEqual("album Mei", album.album)

    def test_drop_feats(self):
        self._setup_config(
            drop_feats_from_fields=["artist"],
        )
        track = TrackInfo(
            track_id="mocktrack", title="foo feat. bar", artist="foo feat. bar"
        )
        album = AlbumInfo(
            album_id="mockrelease",
            album="album feat. bar",
            artist="foo feat. bar",
            tracks=[track],
        )
        self.plugin._mb_track_extract(
            {
                "id": "mocktrack",
                "artist-credit": [
                    {
                        "artist": {"name": "foo"},
                    },
                    " feat. ",
                    {"artist": {"name": "bar"}},
                ],
            }
        )
        self.plugin._mb_album_extract(
            {
                "id": "mockrelease",
                "artist-credit": [
                    {
                        "artist": {"name": "foo"},
                    },
                    " feat. ",
                    {"artist": {"name": "bar"}},
                ],
            }
        )
        self.plugin._albuminfo_received(album)

        # should only remove from configured fields
        self.assertEqual(track.title, "foo feat. bar")
        self.assertEqual(album.album, "album feat. bar")

        # artist works for both track and album
        self.assertEqual(track.artist, "foo")
        self.assertEqual(album.artist, "foo")

    # TODO:
    # it actually works! but, Unihandecode isn't actually much of an improvement. readings
    # in japanese require way too much context, so it's probably better to just keep the
    # original kanji if there's no actual localization
    #
    #  - figure out what to do about single-track imports: when does that code run? what heuristic can i use?
    #    do i need to make extra api calls, or does beets already fetch a sampling of releases that i can use
    #    to determine language / script with some heuristic?


def suite():
    return unittest.TestLoader().loadTestsFromName(__name__)


if __name__ == "__main__":
    unittest.main(defaultTest="suite")
