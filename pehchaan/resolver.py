"""The incremental resolver: decides which identity each new record belongs to.

For every incoming record:
  1. normalise it
  2. look up candidate records through blocking keys (an in-memory index)
  3. score the record against each candidate
  4. decide:
       no matches                     -> create a new identity
       matches in ONE identity        -> join it
       matches in SEVERAL identities  -> this record is a bridge: MERGE them

Merging is the dangerous step. A single wrong match can chain two different people
together (A~B, B~C, so A=C). We log every link with its evidence so merges can be
explained and audited later.

The in-memory index is rebuilt from the database on startup (warm_start), so the
stream processor can be restarted safely at any time.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass

from pehchaan.config import BLOCK_CAP
from pehchaan.matching import MatchResult, blocking_keys, score_pair
from pehchaan.normalize import NormRecord, normalize
from pehchaan.store import Store

log = logging.getLogger(__name__)


@dataclass
class ResolveOutcome:
    record_id: str
    identity_id: str | None
    action: str              # "new", "joined", "merged", "duplicate"
    matched_records: int = 0
    merged_identities: int = 0
    candidates: int = 0
    skipped_blocks: int = 0


class Resolver:
    def __init__(self, store: Store, block_cap: int = BLOCK_CAP):
        self.store = store
        self.block_cap = block_cap
        self.records: dict[str, NormRecord] = {}
        self.blocks: dict[str, list[str]] = defaultdict(list)
        self.identity_of: dict[str, str] = {}
        self.members: dict[str, set[str]] = defaultdict(set)
        self.next_number = 1

    def warm_start(self) -> int:
        """Rebuild the in-memory index from the database. Returns records loaded."""
        for norm, identity_id in self.store.load_state():
            self._index(norm, identity_id)
        self.next_number = self.store.max_identity_number() + 1
        log.info("Warm start: %d records, %d identities", len(self.records), len(self.members))
        return len(self.records)

    def _index(self, norm: NormRecord, identity_id: str) -> None:
        self.records[norm.record_id] = norm
        self.identity_of[norm.record_id] = identity_id
        self.members[identity_id].add(norm.record_id)
        for key in blocking_keys(norm):
            self.blocks[key].append(norm.record_id)

    def _new_identity_id(self) -> str:
        identity_id = f"PID{self.next_number:07d}"
        self.next_number += 1
        return identity_id

    def process(self, canonical: dict) -> ResolveOutcome:
        """Resolve one canonical record. The caller is responsible for committing."""
        record_id = canonical["record_id"]
        if record_id in self.records or self.store.has_record(record_id):
            # Idempotency: Kafka may redeliver a message after a crash. Same input, no change.
            return ResolveOutcome(record_id, self.identity_of.get(record_id), "duplicate")

        norm = normalize(canonical)
        at = norm.ingested_at

        candidates: set[str] = set()
        skipped = 0
        for key in blocking_keys(norm):
            block = self.blocks.get(key, [])
            if len(block) > self.block_cap:
                skipped += 1  # a "hub" value shared by too many records; comparing is useless
                continue
            candidates.update(block)

        matches: list[tuple[str, MatchResult]] = []
        for other_id in candidates:
            result = score_pair(norm, self.records[other_id])
            if result.is_match:
                matches.append((other_id, result))

        target_ids = sorted({self.identity_of[rid] for rid, _ in matches})
        self.store.save_record(norm)

        if not target_ids:
            identity_id = self._new_identity_id()
            self.store.create_identity(identity_id, at)
            action, reason = "new", "no matching records"
        elif len(target_ids) == 1:
            identity_id = target_ids[0]
            action, reason = "joined", f"matched {len(matches)} record(s)"
        else:
            # Survivor = the identity with the most records (ties: the oldest id).
            identity_id = max(target_ids, key=lambda i: (len(self.members[i]), -int(i[3:])))
            for absorbed in target_ids:
                if absorbed == identity_id:
                    continue
                self.store.merge_identity(absorbed, identity_id, at)
                for rid in self.members.pop(absorbed):
                    self.identity_of[rid] = identity_id
                    self.members[identity_id].add(rid)
            action = "merged"
            reason = f"bridged {len(target_ids)} identities via {len(matches)} matching record(s)"

        self.store.assign(record_id, identity_id, at, reason)
        for other_id, result in matches:
            self.store.add_link(other_id, record_id, result, at)
        self._index(norm, identity_id)

        return ResolveOutcome(record_id, identity_id, action, len(matches),
                              len(target_ids) if action == "merged" else 0, len(candidates), skipped)
