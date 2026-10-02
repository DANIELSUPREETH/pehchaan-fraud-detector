from pehchaan.normalize import (hash_identifier, name_tokens, normalize_address, normalize_email,
                                normalize_phone, parse_dob)
from pehchaan.phonetic import indic_key
from pehchaan.similarity import jaro_winkler, name_similarity


def test_phone_formats_all_normalise_to_one_value():
    formats = ["+91 98450 12345", "098450 12345", "9845012346", "+919845012346", "98450-12345", "91-9845012345"]
    results = {normalize_phone(f) for f in formats}
    assert results == {"+919845012345", "+919845012346"}


def test_junk_and_invalid_phones_rejected():
    assert normalize_phone("9999999999") is None      # placeholder
    assert normalize_phone("9876543210") is None      # the classic "type 9-8-7-6..." placeholder
    assert normalize_phone("1234567890") is None      # does not start with 6-9
    assert normalize_phone("98765") is None           # too short
    assert normalize_phone(None) is None


def test_dob_formats():
    for raw in ["1999-04-12", "12/04/1999", "12-04-1999", "12 Apr 1999"]:
        assert parse_dob(raw) == "1999-04-12"
    assert parse_dob("not a date") is None


def test_address_normalisation_handles_abbreviations_and_pincode():
    a, pin_a = normalize_address("No. 14, Gandhi Ngr Rd, Adyar - 600020")
    b, pin_b = normalize_address("14, GANDHI NAGAR ROAD, ADYAR", "600020")
    assert a == b == "14 gandhi nagar road adyar"
    assert pin_a == pin_b == "600020"


def test_email_and_name_tokens():
    assert normalize_email("  Karthik.R@Mail.Example ") == "karthik.r@mail.example"
    assert normalize_email("not-an-email") is None
    assert name_tokens("Dr. KARTHIK.R_99") == ["karthik", "r"]


def test_government_id_is_hashed_consistently():
    assert hash_identifier("abcde1234f") == hash_identifier("ABCDE 1234F")
    assert "ABCDE" not in hash_identifier("ABCDE1234F")


def test_phonetic_key_groups_transliterations():
    assert indic_key("Lakshmi") == indic_key("Laxmi")
    assert indic_key("Mohd") == indic_key("Muhammad") == indic_key("Mohammed")
    assert indic_key("Sriram") == indic_key("Shriram") == indic_key("Sreeram")
    assert indic_key("Choudhary") == indic_key("Chowdhury")
    assert indic_key("Karthik") != indic_key("Priya")


def test_jaro_winkler_known_value():
    assert round(jaro_winkler("martha", "marhta"), 3) == 0.961  # textbook example


def test_name_similarity_cases():
    t = name_tokens
    assert name_similarity(t("R. Karthik"), t("Karthik Ramesh")) >= 0.9   # initial + reordering
    assert name_similarity(t("Sharma Deepak"), t("Dipak Sharma")) >= 0.9  # variant + reordering
    assert name_similarity(t("Ramesh Sharma"), t("Rahul Sharma")) <= 0.6  # father / son
    assert name_similarity(t("R. Karthik"), t("R. Priya")) <= 0.6         # siblings
