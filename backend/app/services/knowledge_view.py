"""Presentation semantics for paper knowledge.

Extraction deliberately keeps a small, evidence-backed vocabulary.  The
reader still needs to communicate a second vocabulary to people: what is the
main contribution, what is a baseline, what is an ablation, and what merely
supports the evaluation.  This module derives that presentation layer from
the stored candidate/relation fields so older papers improve immediately and
the extraction contract can evolve independently.
"""

from __future__ import annotations

import re
import unicodedata


_ABLATION_MARKERS = (
    "ablation",
    "-im",
    " im",
    "w/o",
    "without",
    "remove",
    "reduced",
    "variant",
)
_BASELINE_NAMES = {
    "act",
    "standard",
    "chain of thought",
    "cot",
    "cot sc",
    "cot sc",
    "chain of thought self consistency",
}
_EVALUATION_TYPES = {"dataset", "benchmark", "task", "metric"}


def _norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[\u2010-\u2015\-_/:]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_ablation(name: str, description: str) -> bool:
    haystack = f"{_norm(name)} {_norm(description)}"
    return any(marker in haystack for marker in _ABLATION_MARKERS)


def classify_candidate(
    entity_type: str,
    name: str,
    role: str = "",
    description: str = "",
) -> tuple[str, str]:
    """Return ``(layer, importance)`` for a paper-local candidate.

    ``layer`` controls where an item is rendered; ``importance`` controls its
    visual weight.  The rules intentionally use evidence already present in
    the database and remain conservative when a model supplied a vague role.
    """

    kind = _norm(entity_type)
    normalized_name = _norm(name)
    normalized_role = _norm(role)

    if kind in _EVALUATION_TYPES:
        # A benchmark/dataset is central to reproducibility, while tasks and
        # metrics describe the evaluation context around it.
        return "evaluation", "core" if kind in {"dataset", "benchmark"} else "supporting"

    if kind == "concept":
        return "component", "supporting"

    if kind == "method":
        if normalized_role == "component":
            return "component", "supporting"
        if _looks_like_ablation(normalized_name, description) or normalized_role in {"ablation", "variant"}:
            return "ablation", "context"
        if normalized_role == "baseline" or normalized_name in _BASELINE_NAMES:
            return "baseline", "supporting"
        if normalized_role == "proposed":
            return "primary", "core"
        # A compared method is usually a baseline, except for explicitly
        # named variants handled above.
        if normalized_role == "compared":
            return "baseline", "supporting"
        return "primary", "supporting"

    if kind == "paper":
        return "comparison", "context"
    if kind == "venue":
        return "evaluation", "context"
    return "comparison", "supporting"


def classify_relation(relation: str, target_name: str = "") -> tuple[str, str]:
    """Return ``(family, importance)`` for an evidence-backed relation."""

    kind = _norm(relation).replace(" ", "_")
    target = _norm(target_name)
    if kind in {"builds_on", "extends", "replaces", "inspired_by"}:
        return "lineage", "core"
    if kind in {"evaluated_on", "uses_dataset"}:
        return "evaluation", "supporting"
    if kind == "requires_concept":
        return "dependency", "supporting"
    if kind in {"compares_with", "contrasts_with"}:
        if _looks_like_ablation(target, ""):
            return "ablation", "context"
        return "comparison", "supporting"
    return "comparison", "supporting"
