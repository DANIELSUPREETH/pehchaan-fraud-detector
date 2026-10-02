"""String similarity functions, written from scratch so you can explain every line.

Jaro-Winkler is the standard choice for names: it tolerates typos and transpositions
("Karthik" vs "Karhtik") and rewards strings that share a prefix, because people
rarely misspell the start of a name.
"""
from pehchaan.phonetic import indic_key


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(max(len(a), len(b)) // 2 - 1, 0)
    a_matched = [False] * len(a)
    b_matched = [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):  # count characters that match within the window
        lo, hi = max(0, i - window), min(len(b), i + window + 1)
        for j in range(lo, hi):
            if not b_matched[j] and b[j] == ch:
                a_matched[i] = b_matched[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    a_seq = [c for c, m in zip(a, a_matched) if m]
    b_seq = [c for c, m in zip(b, b_matched) if m]
    transpositions = sum(x != y for x, y in zip(a_seq, b_seq)) / 2
    return (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3


def jaro_winkler(a: str, b: str, prefix_weight: float = 0.1) -> float:
    score = jaro(a, b)
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return score + prefix * prefix_weight * (1 - score)


def token_similarity(a: str, b: str) -> float:
    """Similarity of two name tokens, aware of initials and phonetic equivalence."""
    if len(a) == 1 or len(b) == 1:  # an initial: 'r' vs 'ramesh'
        return 0.9 if a[0] == b[0] else 0.0
    if a == b:
        return 1.0
    score = jaro_winkler(a, b)
    key_a, key_b = indic_key(a), indic_key(b)
    if key_a == key_b and len(key_a) >= 2:
        score = max(score, 0.95)  # 'laxmi' and 'lakshmi' sound identical
    return score


def name_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Order-independent name similarity between 0 and 1.

    Each token of the shorter name is greedily paired with its best unused partner
    in the longer name, and the scores are averaged. So 'R. Karthik' vs 'Karthik Ramesh'
    pairs r~ramesh (0.9) and karthik~karthik (1.0): 0.95.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    short, long_ = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    # Pair full tokens first, so initials can't steal a partner a full token needs
    order = sorted(range(len(short)), key=lambda i: len(short[i]) == 1)
    used: set[int] = set()
    total = 0.0
    worst = 1.0
    for i in order:
        best, best_j = 0.0, None
        for j, candidate in enumerate(long_):
            if j in used:
                continue
            s = token_similarity(short[i], candidate)
            if s > best:
                best, best_j = s, j
        if best_j is not None:
            used.add(best_j)
        total += best
        worst = min(worst, best)
    average = total / len(short)
    # One clearly conflicting token is a strong signal of a DIFFERENT person.
    # Without this cap, 'Ramesh Sharma' vs 'Rahul Sharma' (father and son) averages
    # to ~0.87 because the shared surname pulls the score up.
    if worst < 0.75:
        return min(average, 0.6)
    return average


def address_similarity(a: str | None, b: str | None) -> float:
    """Jaccard overlap of address words (0 to 1)."""
    if not a or not b:
        return 0.0
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / len(sa | sb)
