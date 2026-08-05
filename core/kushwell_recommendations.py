from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


KUSHWELL_PROJECT_ROOT = Path(
    "C:/Users/Kushwell"
)


OUTCOME_ALIASES = {
    "sleep": {
        "sleep",
        "insomnia",
        "difficulty falling asleep",
        "difficulty staying asleep",
        "restless sleep",
    },
    "pain_control": {
        "pain",
        "back pain",
        "chronic pain",
        "arthritis",
        "joint pain",
        "muscle pain",
        "inflammation",
        "headache",
        "migraine",
    },
    "anxiety": {
        "anxiety",
        "anxious",
        "stress",
        "calm",
        "relaxation",
    },
    "appetite": {
        "appetite",
        "poor appetite",
        "appetite loss",
        "hunger",
        "nausea",
    },
    "mood": {
        "mood",
        "depression",
        "uplift",
        "emotional wellbeing",
    },
    "energy": {
        "energy",
        "fatigue",
        "low energy",
        "motivation",
    },
    "focus": {
        "focus",
        "clarity",
        "concentration",
    },
}


class KushwellRecommendationError(
    RuntimeError
):
    pass


def _ensure_import_path() -> None:
    root = str(KUSHWELL_PROJECT_ROOT)

    if root not in sys.path:
        sys.path.insert(0, root)


def _extract_outcomes(
    question: str,
) -> list[str]:
    text = re.sub(
        r"\s+",
        " ",
        str(question or "").lower(),
    ).strip()

    outcomes = []

    for canonical, aliases in OUTCOME_ALIASES.items():
        if any(alias in text for alias in aliases):
            outcomes.append(canonical)

    return outcomes


def _safe_value(
    value: Any,
) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            _safe_value(item)
            for item in value
        ]

    return str(value)


def _first_attr(
    obj,
    names: tuple[str, ...],
    default=None,
):
    for name in names:
        try:
            value = getattr(
                obj,
                name,
                None,
            )

            if value is not None:
                return value

        except Exception:
            continue

    return default


def _serialize_contribution(
    item: dict,
) -> dict:
    return {
        key: _safe_value(value)
        for key, value in item.items()
        if key
        in {
            "terpene_feature",
            "chemical_key",
            "chemotype",
            "chemical_strength",
            "indication_weight",
            "signal",
            "contribution",
            "source",
            "patient_weight",
            "literature_weight",
            "chemical_outcome",
            "patient_evidence_note",
        }
    }


def _serialize_ranked_product(
    row: dict,
    rank: int,
) -> dict:
    product = row.get("product")

    top_contributors = (
        row.get("top_contributors")
        or row.get("contributions")
        or []
    )

    counter_contributors = (
        row.get("counter_contributors")
        or []
    )

    return {
        "rank": rank,
        "product_id": _first_attr(
            product,
            ("id",),
        ),
        "product_name": _first_attr(
            product,
            (
                "product_name",
                "name",
                "display_name",
                "title",
            ),
            "Unknown product",
        ),
        "brand": _first_attr(
            product,
            (
                "brand",
                "manufacturer",
            ),
        ),
        "category": _first_attr(
            product,
            (
                "category",
                "product_type",
                "form",
            ),
        ),
        "score": _safe_value(
            row.get("score")
        ),
        "base_score": _safe_value(
            row.get("base_score")
        ),
        "recommendation_confidence": _safe_value(
            row.get(
                "recommendation_confidence"
            )
        ),
        "attribution_confidence": _safe_value(
            row.get(
                "attribution_confidence"
            )
        ),
        "chemical_outcome_status": row.get(
            "chemical_outcome_status",
            "none",
        ),
        "evidence_summary": _safe_value(
            row.get("evidence_summary")
        ),
        "top_contributors": [
            _serialize_contribution(item)
            for item in top_contributors[:5]
            if isinstance(item, dict)
        ],
        "counter_contributors": [
            _serialize_contribution(item)
            for item in counter_contributors[:5]
            if isinstance(item, dict)
        ],
    }


def _build_profile(
    ranked_rows: list[dict],
) -> list[dict]:
    totals: dict[str, dict] = defaultdict(
        lambda: {
            "weighted_contribution": 0.0,
            "appearances": 0,
            "sources": set(),
        }
    )

    for row in ranked_rows[:10]:
        contributions = (
            row.get("top_contributors")
            or row.get("contributions")
            or []
        )

        for item in contributions:
            if not isinstance(item, dict):
                continue

            chemical = (
                item.get("terpene_feature")
                or item.get("chemical_key")
            )

            if not chemical:
                continue

            contribution = float(
                item.get("contribution")
                or 0.0
            )

            totals[chemical][
                "weighted_contribution"
            ] += contribution

            totals[chemical][
                "appearances"
            ] += 1

            source = item.get("source")

            if source:
                totals[chemical][
                    "sources"
                ].add(source)

    rows = []

    for chemical, stats in totals.items():
        rows.append(
            {
                "chemical_key": chemical,
                "weighted_contribution": round(
                    stats[
                        "weighted_contribution"
                    ],
                    4,
                ),
                "appearances": stats[
                    "appearances"
                ],
                "sources": sorted(
                    stats["sources"]
                ),
            }
        )

    rows.sort(
        key=lambda item: item[
            "weighted_contribution"
        ],
        reverse=True,
    )

    return rows[:12]


def query_recommendations(
    args: dict | None = None,
) -> dict:
    args = dict(args or {})

    question = str(
        args.get("question")
        or args.get("query")
        or ""
    ).strip()

    outcomes = args.get("outcomes")

    if isinstance(outcomes, str):
        outcomes = [outcomes]

    if not isinstance(outcomes, list):
        outcomes = []

    outcomes = [
        str(outcome).strip().lower()
        for outcome in outcomes
        if str(outcome).strip()
    ]

    if not outcomes:
        outcomes = _extract_outcomes(
            question
        )

    if not outcomes:
        return {
            "status": "partial",
            "question": question,
            "outcomes": {},
            "warnings": [
                (
                    "No supported treatment outcome "
                    "could be resolved."
                )
            ],
        }

    try:
        limit_per_outcome = int(
            args.get("limit_per_outcome")
            or 5
        )
    except (TypeError, ValueError):
        limit_per_outcome = 5

    limit_per_outcome = max(
        1,
        min(limit_per_outcome, 20),
    )

    try:
        candidate_limit = int(
            args.get("candidate_limit")
            or 2000
        )
    except (TypeError, ValueError):
        candidate_limit = 2000

    candidate_limit = max(
        50,
        min(candidate_limit, 15000),
    )

    _ensure_import_path()

    previous_skip = os.environ.get(
        "KUSHWELL_SKIP_BRAIN_AUTOSTART"
    )

    os.environ[
        "KUSHWELL_SKIP_BRAIN_AUTOSTART"
    ] = "1"

    try:
        from app import create_app
        from app.models import Product
        from app.services.recommendation_engine import (
            rank_products_for_symptom,
        )

        app = create_app()

    except Exception as exc:
        raise KushwellRecommendationError(
            "Unable to initialize the Kushwell "
            f"recommendation engine: {exc}"
        ) from exc

    finally:
        if previous_skip is None:
            os.environ.pop(
                "KUSHWELL_SKIP_BRAIN_AUTOSTART",
                None,
            )
        else:
            os.environ[
                "KUSHWELL_SKIP_BRAIN_AUTOSTART"
            ] = previous_skip

    payload = {
        "status": "success",
        "question": question,
        "engine": (
            "app.services."
            "recommendation_engine"
        ),
        "outcomes": {},
        "warnings": [],
    }

    try:
        with app.app_context():
            query = Product.query

            try:
                query = query.filter(
                    Product.chem_profile.has()
                )
            except Exception:
                pass

            products = query.limit(
                candidate_limit
            ).all()

            products = [
                product
                for product in products
                if getattr(
                    product,
                    "chem_profile",
                    None,
                )
            ]

            payload["candidate_count"] = len(
                products
            )

            for outcome in outcomes:
                ranked = (
                    rank_products_for_symptom(
                        products=products,
                        symptom_id=outcome,
                    )
                )

                ranked = [
                    row
                    for row in ranked
                    if float(
                        row.get("score")
                        or 0.0
                    )
                    > 0
                ]

                top_rows = ranked[
                    :limit_per_outcome
                ]

                payload["outcomes"][
                    outcome
                ] = {
                    "recommendation_source": (
                        "blended_heatmap"
                    ),
                    "chemical_profile": (
                        _build_profile(ranked)
                    ),
                    "products": [
                        _serialize_ranked_product(
                            row=row,
                            rank=index,
                        )
                        for index, row in enumerate(
                            top_rows,
                            start=1,
                        )
                    ],
                    "product_count": len(
                        top_rows
                    ),
                }

                if not top_rows:
                    payload["warnings"].append(
                        (
                            "The recommendation engine "
                            f"returned no positive-scoring "
                            f"products for {outcome}."
                        )
                    )

    except Exception as exc:
        raise KushwellRecommendationError(
            "Kushwell recommendation query "
            f"failed: {exc}"
        ) from exc

    return payload