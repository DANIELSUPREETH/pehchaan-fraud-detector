"""Central configuration. Every value can be overridden with an environment variable,
so the same code runs on your laptop (SQLite, no Docker) and in Docker (Postgres + Kafka)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("PEHCHAAN_DATA_DIR", PROJECT_ROOT / "data"))

# Database: SQLite for local/offline runs, PostgreSQL in Docker.
DB_URL = os.getenv("PEHCHAAN_DB_URL", f"sqlite:///{DATA_DIR / 'pehchaan.db'}")

# Kafka
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
SOURCES = ["bank_kyc", "telecom", "ecommerce"]
RAW_TOPICS = {s: f"pehchaan.raw.{s}" for s in SOURCES}
DLQ_TOPIC = "pehchaan.dlq"
CONSUMER_GROUP = "pehchaan-resolver"

# Matching
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "5.0"))  # total evidence score needed
NAME_MIN_SIMILARITY = float(os.getenv("NAME_MIN_SIMILARITY", "0.80"))  # names must agree
BLOCK_CAP = int(os.getenv("BLOCK_CAP", "200"))  # skip blocks bigger than this (hub protection)

# PII: government IDs are hashed with this salt before storage. Change it in real use.
PII_SALT = os.getenv("PII_SALT", "dev-salt-change-me")
