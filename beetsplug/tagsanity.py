from functools import reduce
from types import NoneType
from typing import List, Union
import unicodedata

from beets.autotag import TrackInfo, AlbumInfo
from beets.plugins import BeetsPlugin
from unihandecode import Unidecoder
from regex import regex
from confuse import Sequence, Choice

AVAILABLE_LANG_CODES = ["ja", "kr", "vn", "zh"]
VALID_NORMALIZE_MODES = ["NFC", "NFKC", "NFD", "NFKD", None]

CONFIG_DEFAULT = {
    "langs_enabled": AVAILABLE_LANG_CODES,
    "tidy_unihandecode": True,
    "drop_feats_from_fields": [
        "artist",
        "artist_sort",
        "title",
    ],
    "simplify_whitespace": True,
    "simplify_hyphens": True,
    "simplify_curly_quotes": True,
    "simplify_brackets": True,
    "left_bracket": "(",
    "right_bracket": ")",
    "unicode_normalization_mode": "NFC",  # NFKC would remove lookalikes, e.g. \u2160 -> "I"
    "process_fields": [
        "arranger",
        "artist_credit",
        "artist",
        "artist_sort",
        "composer",
        "composer_sort",
        "disctitle",
        "lyricist",
        "title",
        "work",
        "work_disambig",
    ],
    "han_preference": "zh",
}
CONFIG_SCHEMA = {
    "langs_enabled": Sequence(Choice(AVAILABLE_LANG_CODES)),
    "tidy_unihandecode": bool,
    "drop_feats_from_fields": Sequence(str),
    "simplify_whitespace": bool,
    "simplify_hyphens": bool,
    "simplify_curly_quotes": bool,
    "simplify_brackets": bool,
    "left_bracket": str,
    "right_bracket": str,
    "unicode_normalization_mode": Choice(VALID_NORMALIZE_MODES),
    "process_fields": Sequence(str),
    "han_preference": Choice(AVAILABLE_LANG_CODES),
}


class TagSanity(BeetsPlugin):
    def __init__(self):
        super(TagSanity, self).__init__()

        # Beets's hook api doesn't give us the information we need at the place
        # where we need it. Instead, we store the AlbumInfo data by its release ID,
        # which we have available in both hooks. All the TrackInfo data is available
        # on the AlbumInfo structure. We can therefore return a value from
        # the `mb_album_extract` hook that will completely update both track and
        # album info.
        self.pending_albums = {}
        self.pending_tracks = {}
        self.track_join_phrases = {}

        self.setup()

    def setup(self):
        # confuse doesn't validate default values specified in schema functions:
        # such as `confuse.String(default=True)` will return `True` if no value
        # is present in the config.
        #
        # additionally, the Sequence type doesn't support a default value. it turns
        # out to be quite difficult to correctly add default values to a subclass
        # of Sequence, due to the way the code is architected. I therefore abandoned
        # creating my own Sequence-with-default class in favor of the following:
        #
        # it's unclear if this is lucky or intentional, but `add` puts new data
        # into the config hierarchy at the _lowest_ priority. this enables us to
        # fill out all our defaults in one fell swoop, and also ensure that they
        # are validated against the declared schema (albeit, at runtime)
        self.config.add(CONFIG_DEFAULT)
        validated = self.config.get(CONFIG_SCHEMA)

        # the set of Unihandecoder-supported languages to transliterate
        self.langs_enabled: List[str] = validated["langs_enabled"]
        self.tidy_unihandecode: bool = validated["tidy_unihandecode"]

        # the list of fields from which to drop featured artist info
        self.drop_feats_from_fields: List[str] = validated["drop_feats_from_fields"]

        # Unicode simplifications
        self.simplify_whitespace: bool = validated["simplify_whitespace"]
        self.simplify_hyphens: bool = validated["simplify_hyphens"]
        self.simplify_curly_quotes: bool = validated["simplify_curly_quotes"]
        self.simplify_brackets: bool = validated["simplify_brackets"]
        self.left_bracket: str = validated["left_bracket"]
        self.right_bracket: str = validated["right_bracket"]

        self.unicode_normalization_mode: str = validated["unicode_normalization_mode"]

        # The set of fields that exist (on both AlbumInfo and TrackInfo)
        # to perform translations on.
        self.process_fields: List[str] = validated["process_fields"]

        # acceptable inputs taken from:
        # https://codeberg.org/miurahr/unihandecode/src/commit/991dd18aac14301f232c04bd87ba6013f6bd5a53/src/unihandecode/__init__.py#L38-L49
        #
        # It's unclear what standard exactly is being used by the "lang" argument of
        # Unicdecoder's constructor. However, Musicbrainz specifies the "language" values
        # in its API as coming from the ISO-639-3 standard, and the "script" values as
        # coming from the ISO 15924 standard.
        #
        # Unihandecoder does not appear to concern itself with scripts, and seems to
        # "automagically" do its best, so we just do _our_ best to map the value
        # taken from Musicbrainz's release data to the most likely Unihandecoder argument
        # to get what we want (which is a correctly romanized output)
        #
        # Unihandecoder's behavior _will_ convert latin letters with diacritic marks to
        # their plain counterpart, so we don't just run everything through it in order
        # to avoid e.g. Ü being turned into U.

        # The ISO_15924 script "Hani" is ambiguous as to what language it is representing. It could be Hanzi, Kanji, or Hanja.
        # Setting this value selects which language to assume when encountering this script, in the absence of all other cues.
        self.han_preference: str = validated["han_preference"]

        # fmt: off
        # Mappings of various representations of languages/scripts to Unihandecoder
        # language arguments.
        self.lang_map = {
            "Hani": self.han_preference,

            "Hrkt": "ja",  # ISO-15924          : Katakana + Hiragana
            "Kana": "ja",  # ISO-15924          : Katakana
            "Hira": "ja",  # ISO-15924          : Hiragana
            "Jpan": "ja",  # ISO-15924          : Han + Hiragana + Katakana
            "ja":   "ja",  # ISO 639-1          : The Japanese language
            "jpn":  "ja",  # ISO 639-3          : The Japanese language
            "jp":   "ja",  # ISO 3166-1 alpha-2 : Japan, the country
        #   "jpn":  "ja",  # ISO 3166-1 alpha-3 : Japan, the country

            "Hang": "kr",  # ISO 15924          : Hangul
            "Kore": "kr",  # ISO 15924          : Hangul + Han
            "ko":   "kr",  # ISO 639-1          : The Korean language
            "kor":  "kr",  # ISO 639-3          : The Korean language
            "kr":   "kr",  # ISO 3166-1 alpha-2 : Republic of Korea, the country
        #   "kor":  "kr",  # ISO 3166-1 alpha-3 : Republic of Korea, the country

            "vi":   "vn",  # ISO 639-1          : The Vietnamese language
            "vie":  "vn",  # ISO 639-3          : The Vietnamese language
            "vn":   "vn",  # ISO 3166-1 alpha-2 : Viet Nam, the country
            "vnm":  "vn",  # ISO 3166-1 alpha-3 : Viet Nam, the country

            "Hans": "zh",  # ISO 15924          : Han (simplified)
            "Hant": "zh",  # ISO 15924          : Han (traditional)
            "zh":   "zh",  # ISO 639-1          : The Chinese language
            "zho":  "zh",  # ISO 639-3          : The Chinese language
            "cdo":  "zh",  # ISO 639-3          : The Chinese language (Min Dong)
            "cjy":  "zh",  # ISO 639-3          : The Chinese language (Jinyu)
            "cmn":  "zh",  # ISO 639-3          : The Chinese language (Mandarin)
            "cnp":  "zh",  # ISO 639-3          : The Chinese language (Northern Ping)
            "cpi":  "zh",  # ISO 639-3          : The Chinese language (Pu-Xian)
            "csp":  "zh",  # ISO 639-3          : The Chinese language (Southern Ping)
            "czh":  "zh",  # ISO 639-3          : The Chinese language (Huizhou)
            "czo":  "zh",  # ISO 639-3          : The Chinese language (Min Zhong)
            "cn":   "zh",  # ISO 3166-1 alpha-2 : China, the country
            "chn":  "zh",  # ISO 3166-1 alpha-3 : China, the country
        }
        # fmt: on

        self.register_listener("trackinfo_received", self._trackinfo_received)
        self.register_listener("mb_track_extract", self._mb_track_extract)
        self.register_listener("albuminfo_received", self._albuminfo_received)
        # self.register_listener("mb_album_extract", self._mb_album_extract)

    def _get_decoder(self, lang, script):
        mapped_lang = None

        if lang and lang in self.lang_map:
            mapped_lang = self.lang_map[lang]
        elif script and script in self.lang_map:
            mapped_lang = self.lang_map[script]

        if mapped_lang in self.langs_enabled:
            return Unidecoder(lang=mapped_lang)

        return None

    def _process_string(self, decoder: Unidecoder, str: str) -> str:
        """Performs the configured transformations on an arbitrary string,
        using the supplied decoder to transliterate into latin script

        Args:
            decoder (Unidecoder): The Unihandecoder instance to use for transliteration
            str (str): The string to process

        Returns:
            str: The processed string
        """
        if self.simplify_whitespace:
            # replace one or more sequential unicode whitespace with a single ascii space
            # and trim the sides
            str = regex.sub(r"\p{Z}+", " ", str)

        if self.simplify_hyphens:
            # replace unicode hyphens with ascii hyphens
            str = regex.sub(r"\p{Pd}", "-", str)

        if self.simplify_curly_quotes:
            # single quotes
            str = regex.sub(r"[\u0060\u00b4\u2018\u2019]", "'", str)
            # double quotes
            str = regex.sub(r"[\u201c\u201d]", '"', str)
            # any other kind of unicode opening / closing quotes
            str = regex.sub(r"[\p{Pi}\p{Pf}]", '"', str)

        if self.simplify_brackets:
            # left-brackets of all kinds
            str = regex.sub(r"\p{Ps}", self.left_bracket, str)
            # right-brackets of all kinds
            str = regex.sub(r"\p{Pe}", self.right_bracket, str)

        if decoder:
            # render text to latin script
            str = decoder.decode(str)
            if self.tidy_unihandecode:
                # clean up artifacts from Unihandecode, such as:
                # "な石" -> "naShaku" -> "na Shaku"
                str = regex.sub(r"(\p{Ll})(\p{Lu})", "\\1 \\2", str)
                # remove extra spaces around punctuation, such as:
                # "(共)" -> "(Kyou )" -> "Kyou"
                str = regex.sub(
                    r"(\p{L})\s+([\p{Pe}\p{Pf}\p{Po}])|([\p{Ps}\p{Pi}])\s+(\p{L})",
                    "\\1\\3\\2\\4",
                    str,
                )

        if self.unicode_normalization_mode is not None:
            # render into a unicode normal form
            str = unicodedata.normalize(self.unicode_normalization_mode, str)
            # clean up misc. control codes, unprintables, broken unicode
            str = regex.sub(r"\p{C}", "", str)

        return str.strip()

    def _process_object(self, decoder: Unidecoder, obj: Union[AlbumInfo, TrackInfo]):
        """Mutates the provided "info" object, setting the values of the configured
        fields to their "cleaned-up" equivalents.

        Args:
            decoder (Unidecoder): The Unihandecoder instance to use for transliteration
            dict (Union[AlbumInfo, TrackInfo]): The info object to process
        """
        for field in self.process_fields:
            if hasattr(obj, field):
                val = getattr(obj, field)
                if isinstance(val, str):
                    clean = self._process_string(decoder, val)
                    if clean != val:
                        setattr(obj, field, clean)

    def _scrub_track_feats(self, info: TrackInfo) -> NoneType:
        """Mutates a track to remove the first join phrase and
           everything afterwards. Inverts the implicit/unconfigurable
           behavior in mb.py

        Args:
            info (TrackInfo): a TrackInfo object
        """

        if info.track_id in self.track_join_phrases:
            join_phrase = self.track_join_phrases.pop(info.track_id)

            for key in self.drop_feats_from_fields:
                if not hasattr(info, key):
                    continue

                val = getattr(info, key)
                setattr(info, key, val.split(join_phrase)[0])

    def _trackinfo_received(self, info: TrackInfo) -> NoneType:
        """Hook callback for when beets has created the initial TrackInfo object.
        Store the data until later.

        Args:
            info (TrackInfo): the initial TrackInfo given by beets
        """
        if info.index is not None:
            # if "index" is set, then this track is being added as part of an album.
            # defer any work to the album handler, so that we know the specific release
            # being added to the library.
            return

        id = info.track_id
        if id:
            self.pending_tracks[
                id
            ] = info  # store the whole info object under the recording id

    def _mb_track_extract(self, data) -> NoneType:
        """Store the join phrase for a given track, in order to more-correctly
           remove it later. This callback gets called before the "received"
           callback, so we can capture the raw join phrase from the API response
           before losing it to rendering all the credits into a string.

        Args:
            data: Musicbrainz API response for a recording
        """
        try:
            join_phrase = next(
                filter(lambda x: isinstance(x, str), data["artist-credit"])
            )
            if join_phrase:
                self.track_join_phrases[data["id"]] = join_phrase

        except (StopIteration, KeyError):
            pass

    def _albuminfo_received(self, info: AlbumInfo) -> NoneType:
        """Hook callback for when beets has created the initial AlbumInfo object.
        Rewrites the configured fields of the album associated with this release and
        also all tracks that are present on that album.

        Args:
            info (AlbumInfo): The AlbumInfo given by beets
        """

        decoder = self._get_decoder(info.language, info.script)

        # this will directly mutate the TrackInfo objects that live on the album; this
        # could potentially produce unexpected results, since beets expects for us to
        # use the trackinfo_received hook to modify tracks. however, we don't know the
        # information we need at that point (language and script are properties of a
        # release, and recordings aren't inherently associated with a single release)
        for track in info.tracks:
            if self.drop_feats_from_fields:
                self._scrub_track_feats(track)
            self._process_object(decoder, track)

        self._process_object(decoder, info)
