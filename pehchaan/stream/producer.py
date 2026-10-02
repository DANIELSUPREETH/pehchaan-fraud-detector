"""Replay generated records into Kafka, one topic per source.

This simulates three upstream systems (bank, telecom, e-commerce) publishing events.
Messages are keyed by record id, so a re-sent record always lands on the same partition.

Usage:
    python -m pehchaan.stream.producer --rate 300          # 300 messages/second
    python -m pehchaan.stream.producer --rate 0 --limit 1000  # as fast as possible
"""
import argparse
import json
import logging
import time

from confluent_kafka import Producer

from pehchaan.config import DATA_DIR, DLQ_TOPIC, KAFKA_BOOTSTRAP, RAW_TOPICS
from pehchaan.contracts import CONTRACTS
from pehchaan.stream.kafka_utils import ensure_topics

log = logging.getLogger("producer")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Publish generated records to Kafka")
    parser.add_argument("--rate", type=float, default=300, help="messages per second (0 = unlimited)")
    parser.add_argument("--limit", type=int, default=0, help="stop after N messages (0 = all)")
    args = parser.parse_args()

    path = DATA_DIR / "records.jsonl"
    if not path.exists():
        raise SystemExit("No data/records.jsonl. Run: python -m pehchaan.generator")

    ensure_topics(KAFKA_BOOTSTRAP, list(RAW_TOPICS.values()) + [DLQ_TOPIC])
    # acks=all + idempotence: the broker confirms every write and never stores duplicates
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP, "acks": "all",
                         "enable.idempotence": True, "linger.ms": 20})
    failures = 0

    def on_delivery(err, msg):
        nonlocal failures
        if err is not None:
            failures += 1
            log.error("Delivery failed for key %s: %s", msg.key(), err)

    sent = 0
    started = time.perf_counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            envelope = json.loads(line)
            id_field = CONTRACTS[envelope["source"]].id_field
            producer.produce(RAW_TOPICS[envelope["source"]], key=envelope["payload"][id_field],
                             value=line.strip().encode("utf-8"), on_delivery=on_delivery)
            producer.poll(0)  # serve delivery callbacks
            sent += 1
            if args.rate > 0:  # pace ourselves to the requested rate
                expected = sent / args.rate
                elapsed = time.perf_counter() - started
                if expected > elapsed:
                    time.sleep(expected - elapsed)
            if sent % 1000 == 0:
                log.info("Sent %d messages", sent)
            if args.limit and sent >= args.limit:
                break
    producer.flush(30)
    log.info("Done: sent %d messages in %.1fs, %d delivery failures",
             sent, time.perf_counter() - started, failures)


if __name__ == "__main__":
    main()
