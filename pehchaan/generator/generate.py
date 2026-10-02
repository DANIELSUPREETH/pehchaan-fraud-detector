"""Synthetic data generator.

Creates "true" people (the ground truth), then emits messy records about them from
three sources that each use a different schema:

  bank_kyc   - full name, date of birth, address, PAN number, mobile
  telecom    - subscriber name, mobile number (msisdn), sometimes date of birth
  ecommerce  - display name, email, phone, shipping address, device id

It also plants two kinds of groups that share phones/devices/addresses:
  families     - legitimate sharing (same home, a shared family phone or laptop)
  fraud rings  - synthetic identities created in a burst, sharing a few phones/devices

Because we know the truth, we can later MEASURE how accurate the matching engine is.

Usage:
    python -m pehchaan.generator --persons 3000 --rings 15 --seed 42
"""
import argparse
import csv
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pehchaan.config import DATA_DIR
from pehchaan.generator.names import (AREAS, EMAIL_DOMAINS, FEMALE_FIRST, MALE_FIRST,
                                      STREET_NAMES, STREET_TYPES, SURNAMES)

START = datetime(2026, 1, 1)
SPAN_DAYS = 180
STATES = ["TN", "KA", "MH", "WB", "TS", "DL"]


@dataclass
class Person:
    person_id: str
    gender: str
    given: str          # canonical given name
    family_token: str   # surname, or father's name for initial-style naming
    style: str          # "surname" or "initial"
    dob: date
    phone: str
    email: str
    address: dict
    device: str
    pan: str
    base_time: datetime
    family_id: str | None = None
    ring_id: str | None = None
    family_phone: str | None = None
    family_device: str | None = None


class Generator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.used_phones: set[str] = set()
        self.used_emails: set[str] = set()
        self.counters = {"BK": 0, "TC": 0, "EC": 0, "P": 0, "D": 0}
        self.persons: list[Person] = []
        self.records: list[dict] = []
        self.truth: list[dict] = []

    # ---------- small random helpers ----------
    def _next(self, prefix: str) -> str:
        self.counters[prefix] += 1
        width = 6 if prefix in ("P", "D") else 7
        return f"{prefix}{'-' if prefix in ('BK', 'TC', 'EC') else ''}{self.counters[prefix]:0{width}d}"

    def new_phone(self) -> str:
        while True:
            p = str(self.rng.choice("6789")) + "".join(self.rng.choice("0123456789") for _ in range(9))
            if p not in self.used_phones and len(set(p)) > 2:
                self.used_phones.add(p)
                return p

    def new_device(self) -> str:
        return "dev_" + "".join(self.rng.choice("0123456789abcdef") for _ in range(12))

    def new_pan(self) -> str:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return ("".join(self.rng.choice(letters) for _ in range(5))
                + "".join(self.rng.choice("0123456789") for _ in range(4)) + self.rng.choice(letters))

    def new_address(self) -> dict:
        return {"house": self.rng.randint(1, 250), "street": self.rng.choice(STREET_NAMES),
                "stype": self.rng.randrange(len(STREET_TYPES)), "area": self.rng.randrange(len(AREAS))}

    def random_dob(self, start_year: int, end_year: int) -> date:
        start = date(start_year, 1, 1)
        return start + timedelta(days=self.rng.randrange((date(end_year, 12, 31) - start).days))

    def random_time(self, start: datetime, max_days: float) -> datetime:
        return start + timedelta(seconds=self.rng.randrange(int(max_days * 86400)))

    def new_email(self, given: str, family: str) -> str:
        for _ in range(100):
            style = self.rng.choice([f"{given}.{family}", f"{given}{family[0]}", f"{given}_{family}",
                                     f"{given}{self.rng.randint(1, 999)}"])
            email = f"{style}@{self.rng.choice(EMAIL_DOMAINS)}"
            if email not in self.used_emails:
                self.used_emails.add(email)
                return email
        raise RuntimeError("could not create unique email")

    # ---------- people ----------
    def new_person(self, gender=None, style=None, family_token=None, dob=None,
                   address=None, base_time=None) -> Person:
        gender = gender or self.rng.choice("MF")
        given = self.rng.choice(list((MALE_FIRST if gender == "M" else FEMALE_FIRST).keys()))
        style = style or ("initial" if self.rng.random() < 0.4 else "surname")
        if family_token is None:
            family_token = (self.rng.choice(list(MALE_FIRST)) if style == "initial"
                            else self.rng.choice(list(SURNAMES)))
        p = Person(
            person_id=self._next("P"), gender=gender, given=given, family_token=family_token,
            style=style, dob=dob or self.random_dob(1960, 2006), phone=self.new_phone(),
            email=self.new_email(given, family_token), address=address or self.new_address(),
            device=self.new_device(), pan=self.new_pan(),
            base_time=base_time or self.random_time(START, SPAN_DAYS - 30),
        )
        self.persons.append(p)
        return p

    def make_family(self, family_id: str) -> None:
        style = "initial" if self.rng.random() < 0.4 else "surname"
        address = self.new_address()
        surname = self.rng.choice(list(SURNAMES))
        father = self.new_person("M", style, surname if style == "surname" else None,
                                 self.random_dob(1960, 1980), address)
        members = [father]
        if self.rng.random() < 0.85:
            members.append(self.new_person("F", style, surname if style == "surname" else None,
                                           self.random_dob(1962, 1982), address))
        # Children: in initial-style naming they carry the father's name, not a surname
        kid_token = surname if style == "surname" else father.given
        for _ in range(self.rng.randint(0, 3)):
            members.append(self.new_person(None, style, kid_token, self.random_dob(1990, 2006), address))
        family_phone = father.phone if self.rng.random() < 0.5 else None
        family_device = father.device if self.rng.random() < 0.3 else None
        for m in members:
            m.family_id, m.family_phone, m.family_device = family_id, family_phone, family_device

    def make_ring(self, ring_id: str) -> None:
        """Synthetic identities: fake names, created in a burst, reusing a few phones/devices."""
        phones = [self.new_phone() for _ in range(2)]
        devices = [self.new_device() for _ in range(self.rng.randint(1, 2))]
        address = self.new_address()
        window_start = START + timedelta(days=self.rng.randint(10, SPAN_DAYS - 25))
        for _ in range(self.rng.randint(4, 9)):
            p = self.new_person(dob=self.random_dob(1995, 2005),
                                address=address if self.rng.random() < 0.7 else None,
                                base_time=self.random_time(window_start, 14))
            p.ring_id = ring_id
            p.phone = self.rng.choice(phones)
            p.device = self.rng.choice(devices)

    # ---------- messy rendering ----------
    def spell(self, canonical: str, table: dict) -> str:
        variants = table.get(canonical, [canonical])
        word = variants[0] if self.rng.random() < 0.6 else self.rng.choice(variants)
        if len(word) > 5 and self.rng.random() < 0.04:  # occasional typo
            i = self.rng.randrange(1, len(word) - 1)
            op = self.rng.choice(["swap", "drop", "double"])
            if op == "swap":
                word = word[:i] + word[i + 1] + word[i] + word[i + 2:]
            elif op == "drop":
                word = word[:i] + word[i + 1:]
            else:
                word = word[:i] + word[i] + word[i:]
        return word

    def render_name(self, p: Person, source: str) -> str:
        g = self.spell(p.given, MALE_FIRST if p.gender == "M" else FEMALE_FIRST)
        f = self.spell(p.family_token, SURNAMES if p.style == "surname" else MALE_FIRST)
        if p.style == "initial":
            options = [f"{f[0]}. {g}", f"{g} {f[0]}", f"{g} {f}", f"{f[0]} {g}"]
            weights = [4, 3, 3, 1]
        else:
            options = [f"{g} {f}", f"{f} {g}", f"{g[0]}. {f}"]
            weights = [16, 2, 1]
        if source == "ecommerce":
            options += [f"{g}.{f[0]}", f"{g}_{f}", g, f"{g}{self.rng.randint(1, 99)}"]
            weights += [2, 2, 2, 1]
        name = self.rng.choices(options, weights)[0]
        case = self.rng.random()
        return name.upper() if case < 0.25 else (name.title() if case < 0.85 else name)

    def render_phone(self, digits: str) -> str:
        fmt = self.rng.choice(["{d}", "+91{d}", "+91 {a} {b}", "0{a} {b}", "{a}-{b}", "91-{d}"])
        return fmt.format(d=digits, a=digits[:5], b=digits[5:])

    def render_dob(self, d: date) -> str:
        if d.day <= 12 and self.rng.random() < 0.03:  # data-entry error: day and month swapped
            d = date(d.year, d.day, d.month)
        return d.strftime(self.rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y"]))

    def render_address(self, a: dict, with_pin: bool) -> str:
        stype_canon, stype_variants = STREET_TYPES[a["stype"]]
        stype = stype_canon if self.rng.random() < 0.5 else self.rng.choice(stype_variants)
        area, pin = AREAS[a["area"]]
        house = self.rng.choice([f"{a['house']}", f"No. {a['house']}", f"#{a['house']}", f"No {a['house']}"])
        text = f"{house}, {a['street']} {stype}, {area}" + (f" - {pin}" if with_pin else "")
        return text.upper() if self.rng.random() < 0.2 else text.title()

    # ---------- records ----------
    def emit(self, p: Person, source: str, payload: dict, at: datetime) -> None:
        record_id = next(v for k, v in payload.items() if k in ("kyc_ref", "connection_id", "customer_id"))
        self.records.append({"source": source, "ingested_at": at.isoformat(), "payload": payload})
        self.truth.append({"record_id": record_id, "person_id": p.person_id,
                           "family_id": p.family_id or "", "ring_id": p.ring_id or ""})

    def record_time(self, p: Person) -> datetime:
        max_days = 4 if p.ring_id else 45
        t = p.base_time + timedelta(seconds=self.rng.randrange(int(max_days * 86400)))
        return min(t, START + timedelta(days=SPAN_DAYS))

    def bank_record(self, p: Person) -> None:
        payload = {
            "kyc_ref": self._next("BK"), "full_name": self.render_name(p, "bank_kyc"),
            "dob": self.render_dob(p.dob), "address_line": self.render_address(p.address, False),
            "pincode": AREAS[p.address["area"]][1], "pan_number": p.pan,
        }
        if self.rng.random() < 0.9:
            payload["mobile"] = self.render_phone(p.phone)
        self.emit(p, "bank_kyc", payload, self.record_time(p))

    def telecom_record(self, p: Person) -> None:
        at = self.record_time(p)
        payload = {
            "connection_id": self._next("TC"), "msisdn": self.render_phone(p.phone),
            "subscriber_name": self.render_name(p, "telecom"),
            "activation_date": at.date().isoformat(), "circle": self.rng.choice(STATES),
        }
        if self.rng.random() < 0.4:
            payload["date_of_birth"] = self.render_dob(p.dob)
        self.emit(p, "telecom", payload, at)

    def ecommerce_record(self, p: Person, email: str | None = None) -> None:
        phone = p.phone
        if p.family_phone and self.rng.random() < 0.4:
            phone = p.family_phone
        rendered_phone = self.render_phone(phone)
        if self.rng.random() < 0.02:
            rendered_phone = "9999999999"  # junk placeholder users type to skip a form field
        device = p.family_device if p.family_device and self.rng.random() < 0.5 else p.device
        payload = {
            "customer_id": self._next("EC"), "display_name": self.render_name(p, "ecommerce"),
            "email": (email or p.email).upper() if self.rng.random() < 0.1 else (email or p.email),
            "phone": rendered_phone, "shipping_address": self.render_address(p.address, True),
            "device_id": device,
        }
        self.emit(p, "ecommerce", payload, self.record_time(p))

    def emit_records(self, p: Person) -> None:
        if p.ring_id:  # synthetic identities rarely pass bank KYC
            self.ecommerce_record(p)
            if self.rng.random() < 0.6:
                self.telecom_record(p)
            if self.rng.random() < 0.1:
                self.bank_record(p)
            return
        emitted = False
        if self.rng.random() < 0.7:
            self.bank_record(p)
            emitted = True
        if self.rng.random() < 0.8:
            self.telecom_record(p)
            emitted = True
            if self.rng.random() < 0.1:  # re-verification creates a second telecom record
                self.telecom_record(p)
        if self.rng.random() < 0.75 or not emitted:
            self.ecommerce_record(p)
            if self.rng.random() < 0.12:  # duplicate shopping account with another email
                self.ecommerce_record(p, self.new_email(p.given, p.family_token))

    def run(self, n_persons: int, n_rings: int) -> None:
        family_n = 0
        while len(self.persons) < n_persons * 0.35:
            family_n += 1
            self.make_family(f"F{family_n:05d}")
        while len(self.persons) < n_persons:
            self.new_person()
        for r in range(1, n_rings + 1):
            self.make_ring(f"R{r:03d}")
        for p in self.persons:
            self.emit_records(p)
        order = sorted(range(len(self.records)), key=lambda i: self.records[i]["ingested_at"])
        self.records = [self.records[i] for i in order]
        self.truth = [self.truth[i] for i in order]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic multi-source identity records")
    parser.add_argument("--persons", type=int, default=3000)
    parser.add_argument("--rings", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    gen = Generator(args.seed)
    gen.run(args.persons, args.rings)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "records.jsonl", "w", encoding="utf-8") as f:
        for rec in gen.records:
            f.write(json.dumps(rec) + "\n")
    with open(DATA_DIR / "ground_truth.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["record_id", "person_id", "family_id", "ring_id"])
        writer.writeheader()
        writer.writerows(gen.truth)

    by_source = {}
    for r in gen.records:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    ring_people = sum(1 for p in gen.persons if p.ring_id)
    print(f"People: {len(gen.persons)} ({ring_people} synthetic identities in {args.rings} rings)")
    print(f"Families: {len({p.family_id for p in gen.persons if p.family_id})}")
    print(f"Records: {len(gen.records)}  by source: {by_source}")
    print(f"Wrote {DATA_DIR / 'records.jsonl'} and {DATA_DIR / 'ground_truth.csv'}")


if __name__ == "__main__":
    main()
