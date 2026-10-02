"""The stream processor: consume records from Kafka and resolve them into identities.

Delivery guarantee: AT-LEAST-ONCE delivery + IDEMPOTENT processing = effectively once.
  1. Process a batch of messages (writes go into an open database transaction).
  2. Commit the database transaction.
  3. THEN commit the Kafka offsets.
If we crash between 2 and 3, Kafka re-delivers those messages on restart. The resolver
sees the record_id already exists and skips it, so nothing is duplicated.

Bad messages (broken JSON, contract violations) go to a dead-letter topic with the
error attached, instead of crashing the pipeline or being silently dropped.

If anything unexpected fails, we roll back and EXIT. Docker restarts the processor,
which rebuilds its memory from the database (warm start) and resumes from the last
committed Kafka offset. Crashing loudly is safer than continuing with a memory state
that no longer matches the database.

Usage:
    python -m pehchaan.stream.processor
"""
import json
import logging
import signal
import time
from collections import Counter

from confluent_kafka import Consumer, Producer, TopicPartition

from pehchaan.config import CONSUMER_GROUP, DLQ_TOPIC, KAFKA_BOOTSTRAP, RAW_TOPICS
from pehchaan.contracts import ContractError, to_canonical
from pehchaan.resolver import Resolver
from pehchaan.store import Store
from pehchaan.stream.kafka_utils import ensure_topics

log = logging.getLogger("processor")

BATCH_SIZE = 200          # commit after this many messages ...
BATCH_SECONDS = 2.0       # ... or after this many seconds, whichever comes first
METRICS_SECONDS = 10.0


class Processor:
    def __init__(self):
        self.running = True
        self.counts: Counter = Counter()
        self.store = Store()
        self.store.init_schema()
        self.resolver = Resolver(self.store)
        self.resolver.warm_start()
        ensure_topics(KAFKA_BOOTSTRAP, list(RAW_TOPICS.values()) + [DLQ_TOPIC])
        self.consumer = Consumer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": CONSUMER_GROUP,
            "enable.auto.commit": False,      # we commit manually, after the database
            "auto.offset.reset": "earliest",  # a brand-new group starts from the beginning
        })
        self.dlq = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP, "acks": "all"})

    def stop(self, *_):
        log.info("Shutdown requested, finishing current batch ...")
        self.running = False

    def send_to_dlq(self, msg, error: str) -> None:
        body = {"error": error, "topic": msg.topic(), "partition": msg.partition(), "offset": msg.offset(),
                "raw": msg.value().decode("utf-8", errors="replace") if msg.value() else None}
        self.dlq.produce(DLQ_TOPIC, key=msg.key(), value=json.dumps(body).encode("utf-8"))
        self.dlq.poll(0)
        self.counts["dead_lettered"] += 1
        log.warning("Dead-lettered %s[%d]@%d: %s", msg.topic(), msg.partition(), msg.offset(), error)

    def handle(self, msg) -> None:
        try:
            envelope = json.loads(msg.value())
            canonical = to_canonical(envelope)
        except (json.JSONDecodeError, UnicodeDecodeError, ContractError, TypeError) as exc:
            self.send_to_dlq(msg, f"{type(exc).__name__}: {exc}")
            return
        if canonical.get("_unexpected_fields"):
            self.counts["schema_additions"] += 1
        outcome = self.resolver.process(canonical)
        self.counts[outcome.action] += 1
        self.counts["skipped_hub_blocks"] += outcome.skipped_blocks

    def commit(self) -> None:
        self.store.commit()                       # 1. database first ...
        self.dlq.flush(10)
        self.consumer.commit(asynchronous=False)  # 2. ... then Kafka offsets

    def consumer_lag(self) -> int:
        """Messages waiting in Kafka that we haven't processed yet."""
        lag = 0
        partitions = self.consumer.assignment()
        for tp, pos in zip(partitions, self.consumer.position(partitions)):
            _, high = self.consumer.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=5)
            if pos.offset >= 0:
                lag += max(high - pos.offset, 0)
            else:
                low, _ = self.consumer.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=5)
                lag += max(high - low, 0)
        return lag

    def run(self) -> None:
        self.consumer.subscribe(list(RAW_TOPICS.values()))
        log.info("Consuming %s as group %s", list(RAW_TOPICS.values()), CONSUMER_GROUP)
        pending = 0
        last_commit = last_metrics = time.monotonic()
        window_start, window_count = time.monotonic(), 0
        try:
            while self.running:
                msg = self.consumer.poll(1.0)
                if msg is not None:
                    if msg.error():
                        log.error("Kafka error: %s", msg.error())
                    else:
                        self.handle(msg)
                        pending += 1
                        window_count += 1
                now = time.monotonic()
                if pending and (pending >= BATCH_SIZE or now - last_commit >= BATCH_SECONDS):
                    self.commit()
                    pending, last_commit = 0, now
                if now - last_metrics >= METRICS_SECONDS:
                    rate = window_count / (now - window_start)
                    log.info("metrics rate=%.0f/s lag=%d totals=%s", rate, self.consumer_lag(), dict(self.counts))
                    last_metrics, window_start, window_count = now, now, 0
            if pending:
                self.commit()
        except Exception:
            log.exception("Unexpected failure; rolling back and exiting so we restart from a clean state")
            self.store.rollback()
            raise
        finally:
            self.consumer.close()
            self.store.close()
            log.info("Stopped. Totals: %s", dict(self.counts))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    processor = Processor()
    signal.signal(signal.SIGINT, processor.stop)
    signal.signal(signal.SIGTERM, processor.stop)
    processor.run()


if __name__ == "__main__":
    main()
