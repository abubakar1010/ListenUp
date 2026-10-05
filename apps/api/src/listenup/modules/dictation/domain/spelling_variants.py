"""British spellings mapped to their American forms, so both score as the same word.

Dictation treats British and American spellings as equal (Architecture 13.1, ADR 0008).
The table is curated, not a dictionary: it lists the regular patterns (-our, -re, -ise,
-yse, doubled l, -ence, -ogue) for words common in spoken English, plus single pairs.
Both texts are mapped to the American form before they are compared. Add a word by
extending the matching list below; the generated table is checked by unit tests.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

# -our (British) and -or (American): colour/color, colours/colors, coloured/colored.
_OUR_STEMS = (
    "arbo",
    "ardo",
    "armo",
    "behavio",
    "cando",
    "clamo",
    "colo",
    "demeano",
    "endeavo",
    "favo",
    "fervo",
    "flavo",
    "harbo",
    "hono",
    "humo",
    "labo",
    "neighbo",
    "odo",
    "paralo",
    "parlo",
    "ranco",
    "rigo",
    "rumo",
    "savo",
    "splendo",
    "tumo",
    "valo",
    "vapo",
    "vigo",
)
_OUR_SUFFIXES = ("", "s", "ed", "ing", "ful", "fully", "less", "ite", "ites", "able", "er", "ers")

# -re (British) and -er (American): centre/center, centres/centers, centred/centered.
_RE_STEMS = (
    "calib",
    "cent",
    "centimet",
    "fib",
    "kilomet",
    "lit",
    "lust",
    "meag",
    "met",
    "millimet",
    "sab",
    "scept",
    "somb",
    "spect",
    "theat",
)
_RE_SUFFIXES = (("re", "er"), ("res", "ers"), ("red", "ered"), ("ring", "ering"))

# -ise (British) and -ize (American) verbs. Only listed stems, because many -ise words
# (advise, promise, surprise, exercise) are spelled the same in both.
_ISE_STEMS = (
    "agonis",
    "apologis",
    "authoris",
    "capitalis",
    "categoris",
    "centralis",
    "civilis",
    "criticis",
    "customis",
    "emphasis",
    "familiaris",
    "fertilis",
    "finalis",
    "globalis",
    "harmonis",
    "hospitalis",
    "idealis",
    "immunis",
    "itemis",
    "legalis",
    "maximis",
    "memoris",
    "minimis",
    "mobilis",
    "modernis",
    "monopolis",
    "normalis",
    "optimis",
    "organis",
    "patronis",
    "penalis",
    "personalis",
    "popularis",
    "prioritis",
    "publicis",
    "realis",
    "recognis",
    "socialis",
    "specialis",
    "standardis",
    "stabilis",
    "summaris",
    "symbolis",
    "sympathis",
    "theoris",
    "utilis",
    "visualis",
)
_ISE_SUFFIXES = (
    ("e", "e"),
    ("ed", "ed"),
    ("es", "es"),
    ("ing", "ing"),
    ("er", "er"),
    ("ers", "ers"),
    ("ation", "ation"),
    ("ations", "ations"),
)

# -yse (British) and -yze (American): analyse/analyze.
_YSE_STEMS = ("anal", "catal", "paral", "breathal", "dial", "electrol", "hydrol")
_YSE_SUFFIXES = ("e", "ed", "es", "ing", "er", "ers")

# A final l doubled before a suffix in British spelling: travelled/traveled.
_DOUBLE_L_STEMS = (
    "cancel",
    "channel",
    "counsel",
    "dial",
    "duel",
    "equal",
    "fuel",
    "grovel",
    "jewel",
    "label",
    "level",
    "marshal",
    "marvel",
    "model",
    "panel",
    "pedal",
    "quarrel",
    "rival",
    "shovel",
    "signal",
    "snorkel",
    "total",
    "travel",
    "tunnel",
    "yodel",
)
_DOUBLE_L_SUFFIXES = ("ed", "ing", "er", "ers", "ous", "or", "ors")

# Words without a regular pattern.
_PAIRS = {
    "acknowledgement": "acknowledgment",
    "acknowledgements": "acknowledgments",
    "aeroplane": "airplane",
    "aeroplanes": "airplanes",
    "ageing": "aging",
    "aluminium": "aluminum",
    "anaemia": "anemia",
    "anaesthesia": "anesthesia",
    "anaesthetic": "anesthetic",
    "analogue": "analog",
    "archaeology": "archeology",
    "axe": "ax",
    "burnt": "burned",
    "catalogue": "catalog",
    "catalogues": "catalogs",
    "cheque": "check",
    "cheques": "checks",
    "cosy": "cozy",
    "defence": "defense",
    "defences": "defenses",
    "dialogue": "dialog",
    "dialogues": "dialogs",
    "doughnut": "donut",
    "doughnuts": "donuts",
    "draught": "draft",
    "draughts": "drafts",
    "dreamt": "dreamed",
    "encyclopaedia": "encyclopedia",
    "enrol": "enroll",
    "enrolment": "enrollment",
    "enrols": "enrolls",
    "foetus": "fetus",
    "fulfil": "fulfill",
    "fulfilment": "fulfillment",
    "fulfils": "fulfills",
    "grey": "gray",
    "greyish": "grayish",
    "instalment": "installment",
    "instalments": "installments",
    "jewellery": "jewelry",
    "judgement": "judgment",
    "judgements": "judgments",
    "kerb": "curb",
    "learnt": "learned",
    "licence": "license",
    "licences": "licenses",
    "manoeuvre": "maneuver",
    "manoeuvres": "maneuvers",
    "mould": "mold",
    "mouldy": "moldy",
    "moustache": "mustache",
    "offence": "offense",
    "offences": "offenses",
    "oestrogen": "estrogen",
    "ok": "okay",
    "paediatric": "pediatric",
    "plough": "plow",
    "practise": "practice",
    "practised": "practiced",
    "practises": "practices",
    "practising": "practicing",
    "pretence": "pretense",
    "programme": "program",
    "programmes": "programs",
    "pyjamas": "pajamas",
    "sceptic": "skeptic",
    "sceptical": "skeptical",
    "skilful": "skillful",
    "smoulder": "smolder",
    "spelt": "spelled",
    "storey": "story",
    "storeys": "stories",
    "sulphur": "sulfur",
    "tyre": "tire",
    "tyres": "tires",
    "wilful": "willful",
    "woollen": "woolen",
}


def _build() -> dict[str, str]:
    table: dict[str, str] = {}

    def add(pairs: Iterable[tuple[str, str]]) -> None:
        for british, american in pairs:
            if british != american:
                table[british] = american

    add((f"{s}ur{x}", f"{s}r{x}") for s in _OUR_STEMS for x in _OUR_SUFFIXES)
    add((f"{s}{gb}", f"{s}{us}") for s in _RE_STEMS for gb, us in _RE_SUFFIXES)
    add((f"{s}{gb}", f"{s[:-1]}z{us}") for s in _ISE_STEMS for gb, us in _ISE_SUFFIXES)
    add((f"{s}ys{x}", f"{s}yz{x}") for s in _YSE_STEMS for x in _YSE_SUFFIXES)
    add((f"{s}l{x}", f"{s}{x}") for s in _DOUBLE_L_STEMS for x in _DOUBLE_L_SUFFIXES)
    add(_PAIRS.items())
    return table


BRITISH_TO_AMERICAN: Mapping[str, str] = MappingProxyType(_build())
