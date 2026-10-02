"""Schema contracts: what each upstream source promises to send us.

Each source uses its own field names. A contract lists the required and optional
fields, and maps them onto one canonical shape the rest of the pipeline understands.

If a message breaks the contract (a required field is missing, or a field is renamed),
we raise ContractError. The stream processor sends that message to a dead-letter
topic instead of crashing or silently storing bad data.
"""
from dataclasses import dataclass


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Contract:
    source: str
    id_field: str
    required: frozenset
    optional: frozenset
    # canonical name -> source field name(s)
    mapping: dict


CONTRACTS = {
    "bank_kyc": Contract(
        source="bank_kyc", id_field="kyc_ref",
        required=frozenset({"kyc_ref", "full_name", "dob", "pan_number"}),
        optional=frozenset({"address_line", "pincode", "mobile"}),
        mapping={"name": "full_name", "dob": "dob", "address": "address_line",
                 "pincode": "pincode", "gov_id": "pan_number", "phones": ["mobile"]},
    ),
    "telecom": Contract(
        source="telecom", id_field="connection_id",
        required=frozenset({"connection_id", "msisdn", "subscriber_name"}),
        optional=frozenset({"activation_date", "circle", "date_of_birth"}),
        mapping={"name": "subscriber_name", "dob": "date_of_birth", "phones": ["msisdn"]},
    ),
    "ecommerce": Contract(
        source="ecommerce", id_field="customer_id",
        required=frozenset({"customer_id", "display_name", "email"}),
        optional=frozenset({"phone", "shipping_address", "device_id"}),
        mapping={"name": "display_name", "email": "email", "address": "shipping_address",
                 "device_id": "device_id", "phones": ["phone"]},
    ),
}


def to_canonical(envelope: dict) -> dict:
    """Validate a raw message {source, ingested_at, payload} and map it to canonical form."""
    source = envelope.get("source")
    if source not in CONTRACTS:
        raise ContractError(f"unknown source: {source!r}")
    if not envelope.get("ingested_at"):
        raise ContractError("missing ingested_at")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")

    contract = CONTRACTS[source]
    missing = sorted(contract.required - payload.keys())
    unexpected = sorted(payload.keys() - contract.required - contract.optional)
    if missing:
        message = f"{source}: missing required field(s) {missing}"
        if unexpected:  # the classic symptom of an upstream rename
            message += f"; unexpected field(s) {unexpected} - possible schema drift"
        raise ContractError(message)
    for name in contract.required:
        if not isinstance(payload[name], str) or not payload[name].strip():
            raise ContractError(f"{source}: field {name!r} must be a non-empty string")

    canonical = {"record_id": f"{payload[contract.id_field]}", "source": source,
                 "ingested_at": envelope["ingested_at"]}
    for canon_field, src in contract.mapping.items():
        if isinstance(src, list):
            canonical[canon_field] = [payload[s] for s in src if payload.get(s)]
        else:
            canonical[canon_field] = payload.get(src)
    # Unknown extra fields with nothing missing are tolerated (additive change), but noted.
    canonical["_unexpected_fields"] = unexpected
    return canonical
