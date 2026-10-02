"""Measure matching accuracy against the generator's ground truth.

We use PAIRWISE metrics, the standard for entity resolution:
  - a "pair" is any two records placed in the same identity
  - precision = of the pairs we linked, how many truly are the same person
  - recall    = of the pairs that truly are the same person, how many we linked

Both can be computed without listing pairs: a group of n records contains n*(n-1)/2 pairs.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path


def pairs(n: int) -> int:
    return n * (n - 1) // 2


def load_ground_truth(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {row["record_id"]: row for row in csv.DictReader(f)}


def pairwise_metrics(predicted: dict[str, str], truth: dict[str, dict]) -> dict:
    common = [r for r in predicted if r in truth]
    pred_sizes = Counter(predicted[r] for r in common)
    true_sizes = Counter(truth[r]["person_id"] for r in common)
    cell_sizes = Counter((predicted[r], truth[r]["person_id"]) for r in common)

    true_positive = sum(pairs(n) for n in cell_sizes.values())
    predicted_pairs = sum(pairs(n) for n in pred_sizes.values())
    actual_pairs = sum(pairs(n) for n in true_sizes.values())
    precision = true_positive / predicted_pairs if predicted_pairs else 1.0
    recall = true_positive / actual_pairs if actual_pairs else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    # Diagnose errors: which identities mix several real people, and who are they?
    people_in_identity: dict[str, set[str]] = defaultdict(set)
    for r in common:
        people_in_identity[predicted[r]].add(truth[r]["person_id"])
    person_meta = {truth[r]["person_id"]: truth[r] for r in common}
    over_merged = {i: p for i, p in people_in_identity.items() if len(p) > 1}
    merge_kinds = Counter()
    for people in over_merged.values():
        families = {person_meta[p]["family_id"] for p in people}
        rings = {person_meta[p]["ring_id"] for p in people}
        if len(families) == 1 and "" not in families:
            merge_kinds["same family"] += 1
        elif len(rings) == 1 and "" not in rings:
            merge_kinds["same fraud ring"] += 1
        else:
            merge_kinds["unrelated people"] += 1

    identities_per_person: dict[str, set[str]] = defaultdict(set)
    for r in common:
        identities_per_person[truth[r]["person_id"]].add(predicted[r])
    split_people = sum(1 for ids in identities_per_person.values() if len(ids) > 1)

    return {
        "records": len(common),
        "true_people": len(true_sizes),
        "predicted_identities": len(pred_sizes),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "over_merged_identities": len(over_merged),
        "over_merge_breakdown": dict(merge_kinds),
        "people_split_across_identities": split_people,
    }
