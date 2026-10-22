"""Reference implementation; deliberately favors inspectability over speed."""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from typing import Callable, Mapping, Protocol


class Backend(Protocol):
    token_text: Mapping[int, str]

    def log_probs(self, prefix: tuple[int, ...]) -> Mapping[int, float]: ...


def normalize_pinyin(value: str) -> str:
    value = value.lower().replace("u:", "v").replace("ü", "v")
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyz' " for c in value):
        raise ValueError("Use untoned full pinyin, optionally separated by spaces/apostrophes")
    value = "'".join(value.replace("'", " ").split())
    if not value:
        raise ValueError("Pinyin cannot be empty")
    return value


class PinyinConstraint:
    def __init__(self, readings: Callable[[str], tuple[str, ...]]):
        self.readings = readings

    @lru_cache(maxsize=32768)
    def advance(self, target: str, positions: frozenset[int], text: str) -> frozenset[int]:
        """Track all legal pronunciation paths, preserving explicit boundaries."""
        if not text:
            return frozenset()
        for char in text:
            next_positions = set()
            for position in positions:
                for reading in self.readings(char):
                    if target.startswith(reading, position):
                        end = position + len(reading)
                        if end < len(target) and target[end] == "'":
                            end += 1
                        next_positions.add(end)
            positions = frozenset(next_positions)
            if not positions:
                break
        return positions


@dataclass(frozen=True)
class Candidate:
    tokens: tuple[int, ...] = ()
    text: str = ""
    positions: frozenset[int] = frozenset({0})
    log_probability: float = 0.0
    search_score: float = 0.0


def group_beam_search(
    backend: Backend,
    constraint: PinyinConstraint,
    pinyin: str,
    *,
    beam_width: int = 4,
    groups: int = 2,
    diversity_penalty: float = 0.5,
    max_steps: int = 32,
) -> list[Candidate]:
    """Mask illegal tokens before pruning; scores use original model log-probs.

    Diversity is a same-step token penalty across groups. Finished hypotheses
    compete for beam slots. Output is deduplicated and ranked by model score.
    This reference version does not implement length normalization or KV reuse.
    """
    if groups < 1 or beam_width < 1 or beam_width % groups:
        raise ValueError("beam_width must be positive and divisible by groups")
    if max_steps < 1 or not isfinite(diversity_penalty) or diversity_penalty < 0:
        raise ValueError("Invalid search budget or diversity penalty")
    target = normalize_pinyin(pinyin)
    width = beam_width // groups
    beams = [[Candidate()] for _ in range(groups)]

    for _ in range(max_steps):
        used_tokens: Counter[int] = Counter()
        step_scores = {}
        all_finished = True
        for group_index, beam in enumerate(beams):
            pool = []
            for candidate in beam:
                if len(target) in candidate.positions:
                    pool.append((candidate, None))
                    continue
                all_finished = False
                if candidate.tokens not in step_scores:
                    step_scores[candidate.tokens] = backend.log_probs(candidate.tokens)
                scores = step_scores[candidate.tokens]
                for token_id, text in backend.token_text.items():
                    positions = constraint.advance(target, candidate.positions, text)
                    if not positions:
                        continue
                    score = scores.get(token_id, float("-inf"))
                    if not isfinite(score):
                        continue
                    pool.append((Candidate(
                        candidate.tokens + (token_id,), candidate.text + text, positions,
                        candidate.log_probability + score,
                        candidate.search_score + score - diversity_penalty * used_tokens[token_id],
                    ), token_id))
            pool.sort(key=lambda item: (-item[0].search_score, item[0].tokens))
            chosen = pool[:width]
            beams[group_index] = [candidate for candidate, _ in chosen]
            used_tokens.update(token for _, token in chosen if token is not None)
        if all_finished:
            break

    unique = {}
    for beam in beams:
        for candidate in beam:
            if len(target) not in candidate.positions:
                continue
            previous = unique.get(candidate.text)
            if previous is None or candidate.log_probability > previous.log_probability:
                unique[candidate.text] = candidate
    return sorted(unique.values(), key=lambda c: (-c.log_probability, c.text))
