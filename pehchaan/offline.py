"""Run the WHOLE pipeline in one process, without Kafka or Docker.

Reads data/records.jsonl in arrival order, resolves every record into the SQLite
store exactly as the stream processor would, then runs the analysis job.
This is the fastest way to experiment with matching rules.

Usage:
    python -m pehchaan.offline            # reuses existing data/records.jsonl
    python -m pehchaan.offline --fresh    # deletes the old database first
"""
import argparse
import json
import logging
import time
from pathlib import Path

from pehchaan.analyze import run_analysis
from pehchaan.config import DATA_DIR, DB_URL
from pehchaan.contracts import ContractError, to_canonical
from pehchaan.resolver import Resolver
from pehchaan.store import Store


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Offline end-to-end run (SQLite, no Kafka)")
    parser.add_argument("--fresh", action="store_true", help="delete the existing SQLite database first")
    args = parser.parse_args()

    records_path = DATA_DIR / "records.jsonl"
    if not records_path.exists():
        raise SystemExit("No data/records.jsonl. Run: python -m pehchaan.generator")
    if args.fresh:
        if not DB_URL.startswith("sqlite:///"):
            raise SystemExit("--fresh only deletes SQLite databases; refusing to touch " + DB_URL)
        db_path = Path(DB_URL[len("sqlite:///"):])
        if db_path.exists():
            db_path.unlink()

    store = Store()
    store.init_schema()
    resolver = Resolver(store)
    resolver.warm_start()

    actions = {}
    contract_errors = 0
    started = time.perf_counter()
    with open(records_path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            try:
                canonical = to_canonical(json.loads(line))
            except ContractError:
                contract_errors += 1
                continue
            outcome = resolver.process(canonical)
            actions[outcome.action] = actions.get(outcome.action, 0) + 1
            if n % 500 == 0:
                store.commit()
                print(f"  processed {n} records ...", flush=True)
    store.commit()
    elapsed = time.perf_counter() - started
    total = sum(actions.values())
    print(f"\nResolved {total} records in {elapsed:.1f}s ({total / elapsed:.0f} records/sec)")
    print(f"Actions: {actions}   contract errors: {contract_errors}\n")

    print(json.dumps(run_analysis(store), indent=2, default=str))
    store.close()


if __name__ == "__main__":
    main()
