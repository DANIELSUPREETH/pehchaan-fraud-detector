"""Small Kafka helpers shared by the producer and the processor."""
import logging

from confluent_kafka.admin import AdminClient, NewTopic

log = logging.getLogger(__name__)


def ensure_topics(bootstrap: str, topics: list[str], partitions: int = 3) -> None:
    """Create topics if they don't exist. Safe to call every time (idempotent)."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = set(admin.list_topics(timeout=15).topics)
    missing = [NewTopic(t, num_partitions=partitions, replication_factor=1)
               for t in topics if t not in existing]
    if not missing:
        return
    for topic, future in admin.create_topics(missing).items():
        try:
            future.result()
            log.info("Created topic %s", topic)
        except Exception as exc:  # another process may have created it at the same moment
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise
