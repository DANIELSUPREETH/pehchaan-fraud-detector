"""Identity graph analysis: families vs fraud rings.

After resolution, each identity is one (hopefully) real person. Now we look at the
GRAPH between identities: two identities are connected if they share a phone, a
device or an address. Connected groups ("components") are found with union-find.

A shared phone is not proof of fraud. Families share phones, homes and laptops.
So each component is scored on behaviour that separates the two:

  fraud rings: accounts appear in a short burst, rarely pass bank KYC,
               and many different people use one device
  families:    members appear over months, most have bank KYC, share one home address

Every point of risk comes with a reason, so an analyst can see WHY a group was flagged.
"""
from collections import Counter, defaultdict
from datetime import datetime

HUB_LIMIT = 50  # an attribute shared by more identities than this is a hub, not a link


class UnionFind:
    """Disjoint-set structure: near-constant-time 'union' and 'find' of groups."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression: point everything at the root
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace(" ", "T"))


def build_identity_profiles(rows: list[dict]) -> dict[str, dict]:
    profiles: dict[str, dict] = defaultdict(lambda: {"records": set(), "sources": set(),
                                                     "first_seen": None, "attrs": set()})
    for row in rows:
        p = profiles[row["identity_id"]]
        p["records"].add(row["record_id"])
        p["sources"].add(row["source"])
        seen = _parse(row["ingested_at"])
        if p["first_seen"] is None or seen < p["first_seen"]:
            p["first_seen"] = seen
        if row["kind"] in ("phone", "device", "address") and row["value"]:
            p["attrs"].add((row["kind"], row["value"]))
    return profiles


def find_components(profiles: dict[str, dict]) -> list[list[str]]:
    by_attr: dict[tuple, list[str]] = defaultdict(list)
    for identity_id, p in profiles.items():
        for attr in p["attrs"]:
            by_attr[attr].append(identity_id)
    uf = UnionFind()
    for identity_id in profiles:
        uf.find(identity_id)
    for ids in by_attr.values():
        if 1 < len(ids) <= HUB_LIMIT:
            for other in ids[1:]:
                uf.union(ids[0], other)
    groups: dict[str, list[str]] = defaultdict(list)
    for identity_id in profiles:
        groups[uf.find(identity_id)].append(identity_id)
    return [sorted(g) for g in groups.values()]


def score_component(ids: list[str], profiles: dict[str, dict]) -> dict:
    n = len(ids)
    first_seen = [profiles[i]["first_seen"] for i in ids]
    span_days = (max(first_seen) - min(first_seen)).total_seconds() / 86400
    kyc_fraction = sum("bank_kyc" in profiles[i]["sources"] for i in ids) / n
    per_attr = Counter(attr for i in ids for attr in profiles[i]["attrs"])
    max_per_device = max((c for (k, _), c in per_attr.items() if k == "device"), default=0)
    max_per_phone = max((c for (k, _), c in per_attr.items() if k == "phone"), default=0)
    max_per_address = max((c for (k, _), c in per_attr.items() if k == "address"), default=0)
    address_share = max_per_address / n

    risk, reasons = 0.0, []
    if span_days <= 21:
        risk += 2
        reasons.append(f"{n} identities first seen within {span_days:.0f} days (burst)")
    if kyc_fraction < 0.3:
        risk += 2
        reasons.append(f"only {kyc_fraction:.0%} have bank KYC")
    if max_per_device >= 4:
        risk += 2
        reasons.append(f"{max_per_device} identities share one device")
    if max_per_phone >= 4:
        risk += 1
        reasons.append(f"{max_per_phone} identities share one phone")
    if address_share >= 0.6 and kyc_fraction >= 0.5:
        risk -= 2
        reasons.append(f"{address_share:.0%} share one home address and most passed KYC (family pattern)")
    if span_days > 60:
        risk -= 1
        reasons.append(f"identities appeared over {span_days:.0f} days (organic growth)")

    if risk >= 4:
        label = "SUSPICIOUS_RING"
    elif risk <= 0:
        label = "LIKELY_FAMILY"
    else:
        label = "REVIEW"
    return {
        "identity_ids": ids, "label": label, "risk_score": risk, "reasons": reasons,
        "features": {"size": n, "first_seen_span_days": round(span_days, 1),
                     "kyc_fraction": round(kyc_fraction, 2), "max_identities_per_device": max_per_device,
                     "max_identities_per_phone": max_per_phone, "address_share": round(address_share, 2)},
    }


def analyze_rings(rows: list[dict], min_size: int = 3) -> list[dict]:
    profiles = build_identity_profiles(rows)
    report = []
    for component in find_components(profiles):
        if len(component) >= min_size:
            report.append(score_component(component, profiles))
    report.sort(key=lambda r: (-r["risk_score"], -r["features"]["size"]))
    for n, row in enumerate(report, start=1):
        row["component_id"] = n
    return report


def evaluate_rings(report: list[dict], predicted: dict[str, str], truth: dict[str, dict]) -> dict:
    """How many planted rings were flagged, and how many families were falsely flagged?"""
    identity_labels: dict[str, Counter] = defaultdict(Counter)
    for record_id, identity_id in predicted.items():
        t = truth.get(record_id)
        if t:
            identity_labels[identity_id][("ring", t["ring_id"]) if t["ring_id"]
                                         else ("family", t["family_id"])] += 1
    flagged_rings, families_flagged, family_components = set(), 0, 0
    for row in report:
        kinds = Counter(identity_labels[i].most_common(1)[0][0] for i in row["identity_ids"]
                        if identity_labels[i])
        if not kinds:
            continue
        (kind, group_id), count = kinds.most_common(1)[0]
        if kind == "ring" and row["label"] == "SUSPICIOUS_RING" and count >= len(row["identity_ids"]) / 2:
            flagged_rings.add(group_id)
        if kind == "family" and group_id:
            family_components += 1
            if row["label"] == "SUSPICIOUS_RING":
                families_flagged += 1
    planted = {t["ring_id"] for t in truth.values() if t["ring_id"]}
    return {
        "planted_rings": len(planted),
        "rings_flagged": len(flagged_rings & planted),
        "ring_recall": round(len(flagged_rings & planted) / len(planted), 3) if planted else None,
        "family_groups_analyzed": family_components,
        "families_falsely_flagged": families_flagged,
        "labels": dict(Counter(r["label"] for r in report)),
    }
