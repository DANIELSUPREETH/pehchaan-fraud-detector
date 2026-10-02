"""A phonetic key tuned for Indian names written in English letters.

Soundex was designed for English surnames: it keeps the first letter and encodes
consonant groups. Indian names transliterated into English vary in different ways:
  - aspirated consonants:   Dhivya / Divya,  Abdhul / Abdul,  Nikhil / Nikil
  - 'sh' vs 's':            Shriram / Sriram,  Sheikh / Shaikh
  - 'ksh' vs 'x':           Lakshmi / Laxmi
  - long vowels:            Aanand / Anand,  Sreeram / Sriram,  Pooja / Puja
  - 'w' vs 'v', 'ck' vs 'k': Karthick / Karthik,  Chowdhury / Choudhary

The key normalises these, then keeps the first letter plus the consonant skeleton.
Names with the same key "sound the same". It is used for blocking and as one input
to name similarity, never as the only evidence.
"""
import re

# Whole-token aliases: abbreviations that no letter rule can recover
ALIASES = {"mohd": "mohammed", "md": "mohammed"}

# Applied in order. Longer patterns first so 'ksh' is handled before 'sh'.
RULES = [
    ("ksh", "x"), ("ck", "k"), ("q", "k"), ("ph", "f"), ("ow", "u"),
    ("sh", "s"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"),
    ("gh", "g"), ("ch", "c"), ("jh", "j"), ("w", "v"), ("z", "j"),
    ("ee", "i"), ("oo", "u"), ("aa", "a"),
]

VOWELS = set("aeiouy")


def indic_key(token: str) -> str:
    """'Lakshmi' -> 'lxm', 'Laxmi' -> 'lxm', 'Muhammad' -> 'mhmd', 'Mohd' -> 'mhmd'."""
    word = re.sub(r"[^a-z]", "", token.lower())
    if not word:
        return ""
    word = ALIASES.get(word, word)
    for old, new in RULES:
        word = word.replace(old, new)
    first, rest = word[0], word[1:]
    skeleton = [c for c in rest if c not in VOWELS]
    key = first + "".join(skeleton)
    # collapse repeated letters: 'mmd' -> 'md', 'aggrvl' -> 'agrvl'
    return re.sub(r"(.)\1+", r"\1", key)
