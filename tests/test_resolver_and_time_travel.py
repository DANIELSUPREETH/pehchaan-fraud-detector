from pehchaan.api import service
from pehchaan.resolver import Resolver
from pehchaan.store import Store


def canonical(record_id, at, name, phones=(), dob=None, email=None, gov_id=None, source="ecommerce"):
    return {"record_id": record_id, "source": source, "ingested_at": at, "name": name,
            "phones": list(phones), "dob": dob, "email": email, "gov_id": gov_id}


def new_resolver():
    store = Store("sqlite:///:memory:")
    store.init_schema()
    return store, Resolver(store)


def test_duplicate_delivery_is_ignored():
    store, resolver = new_resolver()
    first = resolver.process(canonical("EC-1", "2026-01-01T00:00:00", "Arun Rao", ["9845012345"]))
    again = resolver.process(canonical("EC-1", "2026-01-01T00:00:00", "Arun Rao", ["9845012345"]))
    assert again.action == "duplicate"
    assert again.identity_id == first.identity_id
    assert store.stats()["records"] == 1


def test_bridge_record_merges_identities_and_history_is_preserved():
    store, resolver = new_resolver()
    # Jan: telecom record with a phone. Feb: e-commerce record with an email. No overlap yet.
    a = resolver.process(canonical("TC-1", "2026-01-10T00:00:00", "Lakshmi Iyer", ["9845012345"],
                                   source="telecom"))
    b = resolver.process(canonical("EC-1", "2026-02-10T00:00:00", "Laxmi Iyer", email="lakshmi@mail.example"))
    assert a.identity_id != b.identity_id
    # March: a record with BOTH the phone and the email proves they are one person.
    c = resolver.process(canonical("EC-2", "2026-03-10T00:00:00", "Lakshmi Aiyer", ["+91 98450 12345"],
                                   email="LAKSHMI@mail.example"))
    store.commit()
    assert c.action == "merged"
    survivor = c.identity_id

    # Today: one identity with all three records
    now = service.identity_view(store, survivor)
    assert now["record_count"] == 3

    # Time travel to 1 March: the two identities were still separate
    absorbed = b.identity_id if survivor == a.identity_id else a.identity_id
    before_survivor = service.identity_view(store, survivor, "2026-03-01")
    before_absorbed = service.identity_view(store, absorbed, "2026-03-01")
    assert before_survivor["record_count"] == 1
    assert before_absorbed["record_count"] == 1 and before_absorbed["status"] == "active"

    # After the merge, the absorbed identity points to the survivor
    assert service.identity_view(store, absorbed)["status"] == "merged"
    assert service.record_view(store, "EC-1", "2026-02-15")["identity_id"] == b.identity_id
    assert service.record_view(store, "EC-1")["identity_id"] == survivor

    # Explanation contains human-readable evidence
    evidence = [e for link in service.explain_view(store, survivor)["links"] for e in link["evidence"]]
    assert any("same email" in e for e in evidence)


def test_search_masks_and_finds_by_any_phone_format():
    store, resolver = new_resolver()
    resolver.process(canonical("TC-1", "2026-01-10T00:00:00", "Arun Rao", ["9845012345"], source="telecom"))
    store.commit()
    found = service.search(store, phone="+91 98450-12345")
    assert len(found["identities"]) == 1
    view = service.identity_view(store, found["identities"][0])
    assert view["records"][0]["phones"] == ["+91******2345"]
