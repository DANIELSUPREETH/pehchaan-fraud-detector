"""Service-layer tests for the endpoints the analyst console uses."""
import pytest

from pehchaan.api import service
from pehchaan.resolver import Resolver
from pehchaan.rings import analyze_rings
from pehchaan.store import Store


def record(record_id, at, name, phones=(), source="ecommerce", device=None, address=None):
    return {"record_id": record_id, "source": source, "ingested_at": at, "name": name,
            "phones": list(phones), "device_id": device, "address": address}


def build_store():
    """Two people with spelling variants, plus a 4-identity 'ring' sharing one device."""
    store = Store("sqlite:///:memory:")
    store.init_schema()
    r = Resolver(store)
    r.process(record("TC-1", "2026-01-05T00:00:00", "Lakshmi Iyer", ["9845098450"], "telecom"))
    r.process(record("EC-1", "2026-01-06T00:00:00", "LAXMI IYER", ["+91 98450 98450"]))
    r.process(record("EC-2", "2026-01-07T00:00:00", "Laxmi Iyer", ["9845098450"]))
    for i, name in enumerate(["Arun Das", "Neha Joshi", "Imran Khan", "Ritu Verma"]):
        r.process(record(f"EC-R{i}", f"2026-03-0{i + 1}T00:00:00", name, [f"70199{i}2331"],
                         device="dev_shared_ring", address="5 tilak road kothrud"))
    store.commit()
    store.save_ring_report("run-test", analyze_rings(store.current_identity_attributes()), "2026-07-01T00:00:00")
    return store


def test_name_search_is_phonetic():
    store = build_store()
    found = service.smart_search(store, "lakshmi iyer")
    assert found["searched_as"] == "name"
    assert len(found["results"]) == 1
    assert found["results"][0]["record_count"] == 3


def test_smart_search_detects_phone_and_email():
    store = build_store()
    assert service.smart_search(store, "+91 98450-98450")["searched_as"] == "phone"
    assert service.smart_search(store, "someone@mail.example")["searched_as"] == "email"
    with pytest.raises(service.BadRequest):
        service.smart_search(store, "   ")


def test_display_name_prefers_most_frequent_spelling():
    assert service.best_name(["SUREESH BANERJEE", "Suresh Banerjee", "Suresh Banerjee"]) == "Suresh Banerjee"
    assert service.best_name(["nikhil_iyer"]) == "nikhil iyer"


def test_ring_detail_has_graph_edges():
    store = build_store()
    rings = service.rings_view(store)
    assert rings["run_id"] == "run-test"
    group = rings["components"][0]
    detail = service.ring_detail(store, "run-test", group["component_id"])
    assert len(detail["nodes"]) == 4
    assert all("device" in e["kinds"] for e in detail["edges"])
    assert len(detail["edges"]) == 6  # every pair of the 4 shares the device


def test_review_is_saved_and_counted():
    store = build_store()
    cid = service.rings_view(store)["components"][0]["component_id"]
    service.review_ring(store, "run-test", cid, "confirmed_fraud", "one device, four names")
    assert service.rings_view(store)["components"][0]["review"]["decision"] == "confirmed_fraud"
    assert service.overview(store)["decisions"] == {"confirmed_fraud": 1}
    service.review_ring(store, "run-test", cid, "false_alarm")  # changing your mind replaces the decision
    assert service.overview(store)["decisions"] == {"false_alarm": 1}


def test_review_validation():
    store = build_store()
    with pytest.raises(service.BadRequest):
        service.review_ring(store, "run-test", 1, "maybe")
    with pytest.raises(service.NotFound):
        service.review_ring(store, "run-test", 999, "false_alarm")


def test_activity_is_newest_first():
    store = build_store()
    recent = service.activity(store, 3)["recent_records"]
    assert [r["record_id"] for r in recent] == ["EC-R3", "EC-R2", "EC-R1"]
