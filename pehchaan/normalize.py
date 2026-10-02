"""Normalisation: turn messy source values into consistent, comparable values.

Matching quality depends more on this step than on any clever algorithm.
"+91 98765 43210", "098765-43210" and "9876543210" must all become the same value,
or the engine will never notice that they are one phone number.
"""
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from pehchaan.config import PII_SALT

HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "smt", "shri", "kum"}

# Placeholder numbers people type to get past a form. Treating them as real phones
# would link thousands of strangers together (a "hub"), so we reject them.
JUNK_PHONES = {"9999999999", "8888888888", "7777777777", "6666666666", "9876543210", "1234567890"}

ADDRESS_ABBREVIATIONS = {
    "rd": "road", "ngr": "nagar", "st": "street", "crs": "cross", "lyt": "layout",
    "apt": "apartment", "opp": "opposite", "mg": "mg",
}
ADDRESS_NOISE_WORDS = {"no", "house", "flat", "door"}

DOB_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%d.%m.%Y"]


@dataclass
class NormRecord:
    """A source record after cleaning. Every source maps into this one shape."""
    record_id: str
    source: str
    ingested_at: str
    display_name: str
    name_tokens: list[str] = field(default_factory=list)
    dob: str | None = None
    phones: list[str] = field(default_factory=list)
    email: str | None = None
    address: str | None = None
    pincode: str | None = None
    id_hash: str | None = None
    device_id: str | None = None
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NormRecord":
        return cls(**d)


def name_tokens(raw: str | None) -> list[str]:
    """'Dr. KARTHIK.R_99' -> ['karthik', 'r']"""
    if not raw:
        return []
    cleaned = re.sub(r"[^a-z]+", " ", raw.lower())
    return [t for t in cleaned.split() if t not in HONORIFICS]


def normalize_phone(raw: str | None) -> str | None:
    """Return '+91XXXXXXXXXX' for a valid Indian mobile number, else None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    if digits in JUNK_PHONES or len(set(digits)) <= 2:
        return None
    return "+91" + digits


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = raw.strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else None


def parse_dob(raw: str | None) -> str | None:
    """Accept several date formats and return ISO 'YYYY-MM-DD', or None if unparseable."""
    if not raw:
        return None
    for fmt in DOB_FORMATS:
        try:
            d = datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
        if date(1900, 1, 1) <= d <= date.today():
            return d.isoformat()
    return None


def normalize_address(raw: str | None, pincode: str | None = None) -> tuple[str | None, str | None]:
    """'No. 14, Gandhi Ngr Rd, Adyar - 600020' -> ('14 gandhi nagar road adyar', '600020')"""
    if not raw:
        return None, pincode
    tokens = re.sub(r"[^a-z0-9]+", " ", raw.lower()).split()
    found_pin = next((t for t in tokens if re.fullmatch(r"\d{6}", t)), None)
    out = []
    for t in tokens:
        if t == found_pin or t in ADDRESS_NOISE_WORDS:
            continue
        out.append(ADDRESS_ABBREVIATIONS.get(t, t))
    return (" ".join(out) or None), (pincode or found_pin)


def hash_identifier(raw: str | None) -> str | None:
    """Government IDs are never stored in clear text: salted SHA-256, truncated.

    Equal IDs still produce equal hashes, so we can match on them without keeping them.
    """
    if not raw:
        return None
    value = re.sub(r"\s", "", raw).upper()
    return hashlib.sha256((PII_SALT + value).encode()).hexdigest()[:24]


def normalize(canonical: dict) -> NormRecord:
    """Normalise a canonical record (see contracts.py) into a NormRecord."""
    flags = []
    phones = []
    for raw_phone in canonical.get("phones") or []:
        p = normalize_phone(raw_phone)
        if p and p not in phones:
            phones.append(p)
        elif raw_phone and not p:
            flags.append("invalid_phone")

    email = normalize_email(canonical.get("email"))
    if canonical.get("email") and not email:
        flags.append("invalid_email")

    dob = parse_dob(canonical.get("dob"))
    if canonical.get("dob") and not dob:
        flags.append("invalid_dob")

    address, pincode = normalize_address(canonical.get("address"), canonical.get("pincode"))
    tokens = name_tokens(canonical.get("name"))
    if not tokens:
        flags.append("missing_name")

    return NormRecord(
        record_id=canonical["record_id"], source=canonical["source"],
        ingested_at=canonical["ingested_at"], display_name=canonical.get("name") or "",
        name_tokens=tokens, dob=dob, phones=phones, email=email, address=address,
        pincode=pincode, id_hash=hash_identifier(canonical.get("gov_id")),
        device_id=canonical.get("device_id"), quality_flags=flags,
    )
