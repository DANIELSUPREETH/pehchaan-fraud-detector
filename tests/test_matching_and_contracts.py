import pytest

from pehchaan.contracts import ContractError, to_canonical
from pehchaan.matching import blocking_keys, score_pair
from pehchaan.normalize import normalize


def rec(record_id, name, phones=(), dob=None, email=None, address=None, gov_id=None, device=None,
        source="ecommerce"):
    return normalize({"record_id": record_id, "source": source, "ingested_at": "2026-01-01T00:00:00",
                      "name": name, "phones": list(phones), "dob": dob, "email": email,
                      "address": address, "gov_id": gov_id, "device_id": device})


def test_same_person_across_sources_matches():
    bank = rec("BK-1", "R. Karthik", ["+91 98450 12345"], "1999-04-12", source="bank_kyc")
    telecom = rec("TC-1", "KARTHICK RAMESH", ["098450-12345"], source="telecom")
    result = score_pair(bank, telecom)
    assert result.is_match, result.reasons


def test_family_members_sharing_phone_and_address_do_not_match():
    father = rec("EC-1", "Ramesh Sharma", ["9845012345"], address="14 Gandhi Road Adyar")
    son = rec("EC-2", "Rahul Sharma", ["9845012345"], address="14 Gandhi Road Adyar")
    assert not score_pair(father, son).is_match


def test_conflicting_dob_blocks_match():
    a = rec("BK-1", "Priya Sharma", ["9845012345"], "1990-01-01", source="bank_kyc")
    b = rec("BK-2", "Priya Sharma", ["9845012345"], "1985-07-19", source="bank_kyc")
    assert not score_pair(a, b).is_match


def test_swapped_day_month_still_counts_as_evidence():
    a = rec("BK-1", "Anand Rao", dob="1990-03-07", source="bank_kyc")
    b = rec("TC-1", "Aanand Rao", dob="1990-07-03", source="telecom")
    assert any("swapped" in r for r in score_pair(a, b).reasons)


def test_blocking_lets_initial_and_full_name_meet():
    a = rec("A", "R. Karthik")
    b = rec("B", "Karthik Ramesh")
    assert blocking_keys(a) & blocking_keys(b)


def test_contract_maps_source_fields():
    canonical = to_canonical({"source": "telecom", "ingested_at": "2026-01-01T00:00:00",
                              "payload": {"connection_id": "TC-1", "msisdn": "9845012345",
                                          "subscriber_name": "Arun A"}})
    assert canonical["record_id"] == "TC-1"
    assert canonical["phones"] == ["9845012345"]
    assert canonical["name"] == "Arun A"


def test_contract_detects_schema_drift():
    with pytest.raises(ContractError, match="schema drift"):
        to_canonical({"source": "telecom", "ingested_at": "2026-01-01T00:00:00",
                      "payload": {"connection_id": "TC-1", "mobile_number": "9845012345",
                                  "subscriber_name": "Arun A"}})


def test_contract_rejects_unknown_source():
    with pytest.raises(ContractError):
        to_canonical({"source": "crm", "ingested_at": "2026-01-01", "payload": {}})
