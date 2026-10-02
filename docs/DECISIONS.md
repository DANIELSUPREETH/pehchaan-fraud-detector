# Decision log

Every non-obvious choice, why it was made, and what it cost. Add an entry whenever
you change a rule, a threshold or a design. Measure before and after.

---

## D1. Rule-based scoring instead of a machine-learning model
**Decision:** score pairs with hand-weighted evidence (name, ID, email, phone, DOB, address, device).
**Why:** every decision can be explained in plain language (`/explain`), which matters in a
regulated domain. There are no labelled real-world pairs to train on.
**Cost:** weights are tuned by judgement. A learned model (e.g. logistic regression on
the same features, trained on the synthetic ground truth) could find better weights.

## D2. Custom phonetic key instead of Soundex
**Decision:** wrote `indic_key` with rules for aspirated consonants (dh/d), sh/s, ksh/x, long vowels.
**Why:** Soundex is designed for English surnames and misses Lakshmi/Laxmi, Dhivya/Divya.
**Measured:** groups 76 of 79 name-variant families. Misses: Subramanian/Subramaniam,
Aishwarya/Ishwarya, Iyer/Aiyer (Jaro-Winkler still scores these above 0.9).
Collision: Sowmya/Shyam share a key (harmless: used for blocking, not as proof).

## D3. "Names must agree" as a hard rule
**Decision:** a match needs total evidence >= 5.0 AND name similarity >= 0.80.
**Why:** family members share phones and addresses. Without the name rule, a father and
son with a shared phone + address + surname would merge.

## D4. Cap name similarity when any token conflicts
**Decision:** if any token pair scores < 0.75, name similarity is capped at 0.6.
**Why:** "Ramesh Sharma" vs "Rahul Sharma" averaged 0.87 because the shared surname
pulled the score up. One conflicting first name is strong evidence of a different person.

## D5. Reject placeholder phone numbers
**Decision:** numbers like 9999999999 and 9876543210 normalise to None.
**Why:** treated as real, they become "hubs" linking unrelated people. Found when my own
test data used 9876543210 and four tests failed.

## D6. Time-versioned assignments (SCD Type 2)
**Decision:** never update or delete an assignment; close it (valid_to) and insert a new one.
**Why:** answers "what did we believe on date X?" for audits and disputed decisions.
**Cost:** more rows; every "current" query needs `valid_to IS NULL`.

## D7. Commit database before Kafka offsets; skip already-seen record ids
**Decision:** at-least-once delivery + idempotent processing.
**Why:** a crash between the two commits re-delivers messages, which are then skipped.
Exactly-once Kafka transactions would not cover the database write anyway.

## D8. Crash on unexpected errors instead of continuing
**Decision:** roll back and exit; Docker restarts the processor, which rebuilds memory
from the database (warm start).
**Why:** after a failed write, in-memory state may no longer match the database.

## D9. Console in plain JavaScript, served by the API
**Decision:** no React, no Node build step. FastAPI serves static files at /ui/; the console
calls only public API endpoints.
**Why:** one command runs everything, in Docker and without it. Using only the public API
proves the API is complete; any screen that needs data the API lacks exposes a gap.
**Cost:** no component framework, so larger UIs would get harder to maintain.

## D10. Phonetic name search via stored keys
**Decision:** store each name token's phonetic key in `record_attributes` (kind `nkey`);
search requires every key in the query to match.
**Why:** uses the existing (kind, value) index, no full-text engine needed, and "laxmi iyer"
finds "Lakshmi Iyer". **Cost:** inherits the key's misses (Iyer vs Aiyer differ).

---

## Open issues (measure, decide, record)

### O1. Spouses with similar first names merge  ← start here
"Navin Verma" merged with "Nandini Verma" (shared family phone + address).
Jaro-Winkler("navin", "nandini") = 0.78, just above the 0.75 conflict cap in
`similarity.py`. Try raising the cap. Re-run `python -m pehchaan.offline --fresh` and
record precision/recall before and after. Watch for typo cases that start failing.

### O2. Same name, same family, no date of birth
Two family members both named "Keerthana Shetty" merge. No identifier separates them.
Is this solvable? What extra data would you need?

### O3. Three planted fraud rings are not flagged
Find them: compare `ground_truth.csv` ring ids with the `/rings` report.
Are they labelled REVIEW? Split into several components? Why?

### O4. Out-of-order arrivals and merges
Kafka does not order messages across topics. `store.assign` prevents negative history
intervals, but a late record can still be attributed to a merge that happened "after" it.
What would event-time processing with a watermark look like here?
