"""API logic in plain Python, kept separate from FastAPI so it is easy to test.

PII handling: phones and emails are masked in every response. Government ID hashes
are never returned at all.
"""
import re
from collections import Counter
from datetime import datetime, timezone

from pehchaan.normalize import name_tokens, normalize_email, normalize_phone
from pehchaan.phonetic import indic_key
from pehchaan.store import Store

REVIEW_DECISIONS = {"confirmed_fraud", "false_alarm"}


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def parse_as_of(value: str | None) -> str | None:
    """Accept '2026-03-01' or '2026-03-01T10:30:00'; return a full ISO timestamp."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        raise BadRequest(f"as_of must be an ISO date or datetime, got {value!r}")


def mask_phone(phone: str) -> str:
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{domain}"


def public_record(row: dict) -> dict:
    n = row["norm"]
    return {
        "record_id": row["record_id"], "source": row["source"], "ingested_at": row["ingested_at"],
        "name_as_written": n["display_name"], "date_of_birth": n["dob"],
        "phones": [mask_phone(p) for p in n["phones"]],
        "email": mask_email(n["email"]) if n["email"] else None,
        "address": n["address"], "pincode": n["pincode"],
        "has_government_id": n["id_hash"] is not None,
        "data_quality_flags": n["quality_flags"],
        "assigned_because": row.get("reason"),
    }


def identity_view(store: Store, identity_id: str, as_of: str | None = None) -> dict:
    info = store.identity_info(identity_id)
    if info is None:
        raise NotFound(f"identity {identity_id} not found")
    as_of = parse_as_of(as_of)
    if as_of is not None and str(info["created_at"]) > as_of:
        raise NotFound(f"identity {identity_id} did not exist yet at {as_of} (created {info['created_at']})")

    merged_into = info["merged_into"]
    merged_at = str(info["merged_at"]) if info["merged_at"] else None
    is_merged = merged_into is not None and (as_of is None or merged_at <= as_of)
    records = [public_record(r) for r in store.identity_records(identity_id, as_of)]
    return {
        "identity_id": identity_id,
        "as_of": as_of or "now",
        "status": "merged" if is_merged else "active",
        "merged_into": merged_into if is_merged else None,
        "created_at": info["created_at"],
        "record_count": len(records),
        "sources": sorted({r["source"] for r in records}),
        "names_seen": sorted({r["name_as_written"] for r in records}),
        "records": records,
    }


def record_view(store: Store, record_id: str, as_of: str | None = None) -> dict:
    as_of = parse_as_of(as_of)
    identity_id = store.identity_of_record(record_id, as_of)
    if identity_id is None:
        raise NotFound(f"record {record_id} not found" + (f" at {as_of}" if as_of else ""))
    return {"record_id": record_id, "as_of": as_of or "now", "identity_id": identity_id}


def history_view(store: Store, identity_id: str) -> dict:
    info = store.identity_info(identity_id)
    if info is None:
        raise NotFound(f"identity {identity_id} not found")
    events = [{"record_id": h["record_id"], "joined_at": h["valid_from"], "left_at": h["valid_to"],
               "reason": h["reason"]} for h in store.identity_history(identity_id)]
    return {"identity_id": identity_id, "created_at": info["created_at"],
            "merged_into": info["merged_into"], "merged_at": info["merged_at"], "events": events}


def explain_view(store: Store, identity_id: str) -> dict:
    """Why are these records one identity? Return every link with its evidence."""
    if store.identity_info(identity_id) is None:
        raise NotFound(f"identity {identity_id} not found")
    record_ids = [r["record_id"] for r in store.identity_records(identity_id)]
    links = store.links_between(record_ids)
    return {"identity_id": identity_id, "record_ids": record_ids,
            "links": [{"records": [l["record_a"], l["record_b"]], "score": l["score"],
                       "evidence": l["reasons"], "linked_at": l["created_at"]} for l in links]}


def best_name(names: list[str]) -> str:
    """Pick the spelling to display: the most frequent one (so a one-off typo loses),
    then the most complete (most words, then longest). Username punctuation becomes spaces."""
    if not names:
        return ""
    cleaned = [" ".join(re.sub(r"[._]+", " ", n).split()) for n in names]
    counts = Counter(c.lower() for c in cleaned)
    return max(cleaned, key=lambda c: (counts[c.lower()], len(name_tokens(c)), len(c)))


def identity_summary(store: Store, identity_id: str) -> dict:
    rows = store.identity_records(identity_id)
    info = store.identity_info(identity_id) or {}
    names = [r["norm"]["display_name"] for r in rows]
    return {"identity_id": identity_id, "display_name": best_name(names).title(),
            "record_count": len(rows), "sources": sorted({r["source"] for r in rows}),
            "status": "merged" if info.get("merged_into") else "active",
            "merged_into": info.get("merged_into")}


def search(store: Store, phone: str | None = None, email: str | None = None, name: str | None = None) -> dict:
    if not phone and not email and not name:
        raise BadRequest("provide phone, email or name")
    record_ids: set[str] = set()
    if phone:
        normalized = normalize_phone(phone)
        if normalized is None:
            raise BadRequest("not a valid Indian mobile number")
        record_ids.update(store.records_with_attribute("phone", normalized))
    if email:
        normalized = normalize_email(email)
        if normalized is None:
            raise BadRequest("not a valid email")
        record_ids.update(store.records_with_attribute("email", normalized))
    if name:
        keys = sorted({indic_key(t) for t in name_tokens(name) if len(t) > 1} - {""})
        if not keys:
            raise BadRequest("name needs at least one word of two or more letters")
        record_ids.update(store.records_matching_name_keys(keys))
    identities = sorted({i for r in record_ids if (i := store.identity_of_record(r))})
    return {"matching_records": len(record_ids), "identities": identities,
            "results": [identity_summary(store, i) for i in identities[:50]],
            "truncated": len(identities) > 50,
            "note": "Several identities sharing one phone is normal for families. See /rings."}


def smart_search(store: Store, q: str) -> dict:
    """One search box: decide whether the query is an email, a phone or a name."""
    q = (q or "").strip()
    if not q:
        raise BadRequest("type a name, phone number or email")
    if "@" in q:
        return {"searched_as": "email", **search(store, email=q)}
    if sum(c.isdigit() for c in q) >= 10:
        return {"searched_as": "phone", **search(store, phone=q)}
    return {"searched_as": "name", **search(store, name=q)}


def rings_view(store: Store, label: str | None = None) -> dict:
    rows = store.latest_ring_report()
    run_id = rows[0]["run_id"] if rows else None
    reviews = store.reviews_for_run(run_id) if run_id else {}
    counts = Counter(r["label"] for r in rows)
    if label:
        rows = [r for r in rows if r["label"] == label.upper()]
    components = []
    for r in rows:
        review = reviews.get(int(r["component_id"]))
        components.append({k: r[k] for k in ("component_id", "label", "risk_score", "reasons",
                                             "features", "identity_ids")}
                          | {"review": {"decision": review["decision"], "note": review["note"],
                                        "reviewed_at": review["reviewed_at"]} if review else None})
    return {"run_id": run_id, "count": len(components), "label_counts": dict(counts),
            "reviewed": len(reviews), "components": components}


def ring_detail(store: Store, run_id: str, component_id: int) -> dict:
    """One group from the analysis, with a graph of how its identities connect."""
    comp = store.ring_component(run_id, component_id)
    if comp is None:
        raise NotFound(f"component {component_id} not found in run {run_id}")
    ids = comp["identity_ids"]
    attrs: dict[str, set] = {i: set() for i in ids}
    for row in store.attributes_for_identities(ids):
        attrs[row["identity_id"]].add((row["kind"], row["value"]))
    nodes = []
    for i in ids:
        summary = identity_summary(store, i)
        records = store.identity_records(i)
        summary["first_seen"] = min((r["ingested_at"] for r in records), default=None)
        nodes.append(summary)
    edges = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            shared = attrs[a] & attrs[b]
            if shared:
                edges.append({"a": a, "b": b, "kinds": sorted({k for k, _ in shared})})
    review = store.reviews_for_run(run_id).get(component_id)
    return {"run_id": run_id, "component_id": component_id, "label": comp["label"],
            "risk_score": comp["risk_score"], "reasons": comp["reasons"], "features": comp["features"],
            "nodes": nodes, "edges": edges,
            "review": {"decision": review["decision"], "note": review["note"],
                       "reviewed_at": review["reviewed_at"]} if review else None}


def review_ring(store: Store, run_id: str, component_id: int, decision: str, note: str = "") -> dict:
    if decision not in REVIEW_DECISIONS:
        raise BadRequest(f"decision must be one of {sorted(REVIEW_DECISIONS)}")
    if store.ring_component(run_id, component_id) is None:
        raise NotFound(f"component {component_id} not found in run {run_id}")
    at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    store.save_review(run_id, component_id, decision, (note or "").strip()[:500], at)
    return {"run_id": run_id, "component_id": component_id, "decision": decision, "reviewed_at": at}


def activity(store: Store, limit: int = 15) -> dict:
    """Latest records and merges, newest first. Refreshing this shows the stream at work."""
    limit = max(1, min(limit, 100))
    return {
        "recent_records": [{"record_id": r["record_id"], "source": r["source"], "ingested_at": r["ingested_at"],
                            "name_as_written": r["norm"]["display_name"], "identity_id": r["identity_id"],
                            "assigned_because": r["reason"]} for r in store.recent_records(limit)],
        "recent_merges": store.recent_merges(limit),
    }


def overview(store: Store) -> dict:
    rings = store.latest_ring_report()
    run_id = rings[0]["run_id"] if rings else None
    reviews = store.reviews_for_run(run_id) if run_id else {}
    suspicious = [r for r in rings if r["label"] == "SUSPICIOUS_RING"]
    return {"stats": store.stats(), "analysis_run": run_id,
            "label_counts": dict(Counter(r["label"] for r in rings)),
            "suspicious_open": sum(1 for r in suspicious if int(r["component_id"]) not in reviews),
            "suspicious_total": len(suspicious),
            "decisions": dict(Counter(r["decision"] for r in reviews.values()))}
