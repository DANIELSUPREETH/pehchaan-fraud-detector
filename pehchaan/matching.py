"""Blocking and pair scoring: deciding whether two records describe the same person.

BLOCKING: comparing every record with every other record is O(n^2). For 1 million
records that is ~500 billion comparisons. Instead each record gets a few cheap
"blocking keys", and we only compare records that share at least one key.

SCORING: for each candidate pair we add up evidence, like a careful human would.
Agreement on strong identifiers adds a lot; agreement on things families share
(phone, address) adds less; contradictions subtract. Every point comes with a
human-readable reason, so the API can explain WHY two records were linked.
"""
from dataclasses import dataclass, field

from pehchaan.config import MATCH_THRESHOLD, NAME_MIN_SIMILARITY
from pehchaan.normalize import NormRecord
from pehchaan.phonetic import indic_key
from pehchaan.similarity import address_similarity, name_similarity


def blocking_keys(r: NormRecord) -> set[str]:
    keys = set()
    for phone in r.phones:
        keys.add(f"ph:{phone}")
    if r.email:
        keys.add(f"em:{r.email}")
    if r.id_hash:
        keys.add(f"id:{r.id_hash}")
    if r.device_id:
        keys.add(f"dv:{r.device_id}")
    # Name keys: phonetic key of each full token + first letter of each other token.
    # 'R. Karthik' and 'Karthik Ramesh' both produce 'nm:krtk|r', so they meet.
    tokens = r.name_tokens
    for i, a in enumerate(tokens):
        if len(a) < 2:
            continue
        ka = indic_key(a)
        for j, b in enumerate(tokens):
            if i != j:
                keys.add(f"nm:{ka}|{b[0]}")
        if r.dob:
            keys.add(f"nd:{ka}|{r.dob}")
    return keys


@dataclass
class MatchResult:
    score: float
    name_similarity: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_match(self) -> bool:
        # Two rules: enough total evidence, AND the names must genuinely agree.
        # The second rule stops family members who share a phone and address from merging.
        return self.score >= MATCH_THRESHOLD and self.name_similarity >= NAME_MIN_SIMILARITY


def _dob_relation(a: str, b: str) -> str:
    if a == b:
        return "same"
    ya, ma, da = a.split("-")
    yb, mb, db = b.split("-")
    if ya == yb and ma == db and da == mb:
        return "swapped"  # classic dd/mm vs mm/dd data-entry error
    return "different"


def score_pair(a: NormRecord, b: NormRecord) -> MatchResult:
    score = 0.0
    reasons = []

    def add(points: float, why: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"{why} ({points:+.1f})")

    name_sim = name_similarity(a.name_tokens, b.name_tokens)
    if name_sim >= 0.92:
        add(3.0, f"names agree strongly ({name_sim:.2f})")
    elif name_sim >= 0.85:
        add(2.0, f"names agree ({name_sim:.2f})")
    elif name_sim >= NAME_MIN_SIMILARITY:
        add(1.0, f"names roughly agree ({name_sim:.2f})")
    elif name_sim < 0.7:
        add(-3.0, f"names disagree ({name_sim:.2f})")

    if a.id_hash and b.id_hash:
        if a.id_hash == b.id_hash:
            add(5.0, "same government ID")
        else:
            add(-6.0, "different government IDs")

    if a.email and b.email and a.email == b.email:
        add(4.0, "same email")

    if set(a.phones) & set(b.phones):
        add(2.5, "shared phone")

    if a.dob and b.dob:
        relation = _dob_relation(a.dob, b.dob)
        if relation == "same":
            add(2.5, "same date of birth")
        elif relation == "swapped":
            add(1.5, "date of birth matches with day/month swapped")
        else:
            add(-4.0, "different dates of birth")

    addr_sim = address_similarity(a.address, b.address)
    if addr_sim >= 0.6:
        add(1.0, f"similar address ({addr_sim:.2f})")
    if a.pincode and b.pincode and a.pincode == b.pincode:
        add(0.5, "same pincode")

    if a.device_id and b.device_id and a.device_id == b.device_id:
        add(1.0, "shared device")

    return MatchResult(score=round(score, 2), name_similarity=round(name_sim, 3), reasons=reasons)
