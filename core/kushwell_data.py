from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text


KUSHWELL_PROJECT_ROOT = Path("C:/Users/Kushwell")
KUSHWELL_APP_ROOT = Path("C:/Users/Kushwell/app")


OUTCOME_ALIASES = {
    "sleep": {
        "sleep",
        "insomnia",
        "night",
        "nighttime",
        "rest",
    },
    "pain": {
        "pain",
        "back pain",
        "chronic pain",
        "arthritis",
        "inflammation",
        "inflammatory",
    },
    "anxiety": {
        "anxiety",
        "anxious",
        "stress",
        "calm",
        "relaxation",
    },
    "mood": {
        "mood",
        "depression",
        "uplift",
        "euphoria",
    },
    "appetite": {
        "appetite",
        "hunger",
        "nausea",
    },
    "energy": {
        "energy",
        "fatigue",
        "motivation",
    },
    "focus": {
        "focus",
        "clarity",
        "concentration",
    },
}


class KushwellDataError(RuntimeError):
    pass


def _ensure_kushwell_import_path() -> None:
    """
    Make the parent directory containing the `app` package importable.

    C:/Users/Kushwell/app is the Flask package, so Python needs
    C:/Users/Kushwell on sys.path.
    """

    project_root = str(KUSHWELL_PROJECT_ROOT)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def _extract_requested_outcomes(question: str) -> list[str]:
    """
    Resolve wellness outcomes from the user's request.

    This intentionally returns canonical domain names rather than
    treating the full user sentence as a literal search phrase.
    """

    normalized = re.sub(
        r"\s+",
        " ",
        str(question or "").lower(),
    ).strip()

    outcomes = []

    for canonical, aliases in OUTCOME_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            outcomes.append(canonical)

    return outcomes


def _choose_column(
    available: set[str],
    candidates: tuple[str, ...],
) -> str | None:
    for candidate in candidates:
        if candidate in available:
            return candidate

    return None


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): _serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            _serialize_value(item)
            for item in value
        ]

    return str(value)


def _find_symptom_rows(
    connection,
    symptom_table: str,
    outcome: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    inspector = inspect(connection)

    columns = {
        column["name"]
        for column in inspector.get_columns(symptom_table)
    }

    id_column = _choose_column(
        columns,
        (
            "id",
            "symptom_id",
        ),
    )

    name_column = _choose_column(
        columns,
        (
            "name",
            "symptom_name",
            "label",
            "display_name",
            "title",
            "slug",
            "key",
        ),
    )

    if not id_column or not name_column:
        return []

    aliases = sorted(
        OUTCOME_ALIASES.get(outcome, {outcome}),
        key=len,
        reverse=True,
    )

    clauses = []
    params: dict[str, Any] = {
        "limit": int(limit),
    }

    for index, alias in enumerate(aliases):
        parameter = f"alias_{index}"
        clauses.append(
            f"LOWER(CAST({name_column} AS TEXT)) LIKE :{parameter}"
        )
        params[parameter] = f"%{alias.lower()}%"

    if not clauses:
        return []

    sql = text(
        f"""
        SELECT
            {id_column} AS symptom_id,
            {name_column} AS symptom_name
        FROM {symptom_table}
        WHERE {" OR ".join(clauses)}
        LIMIT :limit
        """
    )

    rows = connection.execute(sql, params).mappings().all()

    return [
        {
            "symptom_id": row.get("symptom_id"),
            "symptom_name": row.get("symptom_name"),
        }
        for row in rows
    ]


def _query_chemical_outcome_rows(
    connection,
    outcome_table: str,
    symptom_rows: list[dict[str, Any]],
    limit: int,
    outcome: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query chemical outcome rows.

    Important:
    chemical_outcome_summary.symptom_id currently stores a text
    outcome/domain key such as "energy", not a numeric symptom ID.
    """

    inspector = inspect(connection)

    columns = {
        column["name"]
        for column in inspector.get_columns(outcome_table)
    }

    chemical_column = _choose_column(
        columns,
        (
            "chemical_key",
            "chemical",
            "feature_key",
            "terpene",
            "terpene_key",
        ),
    )

    outcome_column = _choose_column(
        columns,
        (
            "symptom_id",
            "outcome_key",
            "domain",
            "domain_key",
            "indication_key",
        ),
    )

    if not chemical_column or not outcome_column:
        return []

    optional_columns = {
        "success_rate": _choose_column(
            columns,
            (
                "success_rate",
                "score",
                "effect_score",
                "weight",
            ),
        ),
        "positive_count": _choose_column(
            columns,
            (
                "positive_count",
                "positive",
            ),
        ),
        "negative_count": _choose_column(
            columns,
            (
                "negative_count",
                "negative",
            ),
        ),
        "total_count": _choose_column(
            columns,
            (
                "total_count",
                "sample_count",
                "n_eff",
            ),
        ),
        "ci_low": _choose_column(
            columns,
            (
                "ci_low",
                "confidence_low",
            ),
        ),
        "ci_high": _choose_column(
            columns,
            (
                "ci_high",
                "confidence_high",
            ),
        ),
        "is_significant": _choose_column(
            columns,
            (
                "is_significant",
                "significant",
            ),
        ),
    }

    select_parts = [
        f"{chemical_column} AS chemical_key",
        f"{outcome_column} AS outcome_key",
    ]

    for alias, column in optional_columns.items():
        if column:
            select_parts.append(f"{column} AS {alias}")
        else:
            select_parts.append(f"NULL AS {alias}")

    canonical_outcome = str(outcome or "").strip().lower()

    if not canonical_outcome:
        return []

    sql = text(
        f"""
        SELECT
            {", ".join(select_parts)}
        FROM {outcome_table}
        WHERE LOWER(CAST({outcome_column} AS TEXT)) = :outcome
        ORDER BY
            CASE
                WHEN success_rate IS NULL THEN 1
                ELSE 0
            END,
            success_rate DESC,
            positive_count DESC
        LIMIT :limit
        """
    )

    rows = connection.execute(
        sql,
        {
            "outcome": canonical_outcome,
            "limit": int(limit),
        },
    ).mappings().all()

    return [
        {
            "chemical_key": row.get("chemical_key"),
            "outcome_key": row.get("outcome_key"),
            "success_rate": _serialize_value(
                row.get("success_rate")
            ),
            "positive_count": _serialize_value(
                row.get("positive_count")
            ),
            "negative_count": _serialize_value(
                row.get("negative_count")
            ),
            "total_count": _serialize_value(
                row.get("total_count")
            ),
            "ci_low": _serialize_value(
                row.get("ci_low")
            ),
            "ci_high": _serialize_value(
                row.get("ci_high")
            ),
            "is_significant": _serialize_value(
                row.get("is_significant")
            ),
        }
        for row in rows
    ]

def query_project_data(args: dict | None = None) -> dict:
    """
    Query live Kushwell chemical-outcome data.

    This is a local Brain tool. It does not go through MCP because
    it queries the Flask application's SQLAlchemy database directly.
    """

    args = dict(args or {})

    question = str(
        args.get("question")
        or args.get("query")
        or ""
    ).strip()

    requested_outcomes = args.get("outcomes")

    if isinstance(requested_outcomes, str):
        requested_outcomes = [requested_outcomes]

    if not isinstance(requested_outcomes, list):
        requested_outcomes = []

    requested_outcomes = [
        str(outcome).strip().lower()
        for outcome in requested_outcomes
        if str(outcome).strip()
    ]

    if not requested_outcomes:
        requested_outcomes = _extract_requested_outcomes(
            question
        )

    if not requested_outcomes:
        return {
            "status": "partial",
            "question": question,
            "outcomes": {},
            "warnings": [
                (
                    "No supported wellness outcomes could be resolved "
                    "from the request."
                )
            ],
        }

    try:
        limit_per_outcome = int(
            args.get("limit_per_outcome") or 10
        )
    except (TypeError, ValueError):
        limit_per_outcome = 10

    limit_per_outcome = max(
        1,
        min(limit_per_outcome, 50),
    )

    _ensure_kushwell_import_path()

    # ---------------------------------------------------------
    # Initialize the Flask app only for database access.
    #
    # Prevent create_app() from starting another Brain process.
    # ---------------------------------------------------------
    previous_skip_value = os.environ.get(
        "KUSHWELL_SKIP_BRAIN_AUTOSTART"
    )

    os.environ["KUSHWELL_SKIP_BRAIN_AUTOSTART"] = "1"

    try:
        from app import create_app
        from app.extensions import db

        app = create_app()

    except Exception as exc:
        raise KushwellDataError(
            f"Unable to initialize Kushwell Flask application: {exc}"
        ) from exc

    finally:
        if previous_skip_value is None:
            os.environ.pop(
                "KUSHWELL_SKIP_BRAIN_AUTOSTART",
                None,
            )
        else:
            os.environ[
                "KUSHWELL_SKIP_BRAIN_AUTOSTART"
            ] = previous_skip_value

    payload: dict[str, Any] = {
        "status": "success",
        "question": question,
        "database_uri": str(
            app.config.get(
                "SQLALCHEMY_DATABASE_URI",
                "",
            )
        ),
        "outcomes": {},
        "warnings": [],
    }

    try:
        with app.app_context():
            inspector = inspect(db.engine)

            table_names = set(
                inspector.get_table_names()
            )

            outcome_table = next(
                (
                    name
                    for name in (
                        "chemical_outcome_summary",
                        "chemical_impact_summary",
                    )
                    if name in table_names
                ),
                None,
            )

            symptom_table = next(
                (
                    name
                    for name in (
                        "symptom",
                        "symptoms",
                        "patient_symptom",
                    )
                    if name in table_names
                ),
                None,
            )

            if not outcome_table:
                payload["status"] = "partial"
                payload["warnings"].append(
                    (
                        "No chemical outcome summary table was found "
                        "in the configured database."
                    )
                )
                return payload

            if not symptom_table:
                payload["status"] = "partial"
                payload["warnings"].append(
                    (
                        "No symptom table was found, so outcome names "
                        "could not be resolved to symptom IDs."
                    )
                )
                return payload

            payload["outcome_table"] = outcome_table
            payload["symptom_table"] = symptom_table

            with db.engine.connect() as connection:
                for outcome in requested_outcomes:
                    symptom_rows = _find_symptom_rows(
                        connection=connection,
                        symptom_table=symptom_table,
                        outcome=outcome,
                    )

                    chemical_rows = _query_chemical_outcome_rows(
                        connection=connection,
                        outcome_table=outcome_table,
                        symptom_rows=symptom_rows,
                        limit=limit_per_outcome,
                        outcome=outcome,
                    )

                    payload["outcomes"][outcome] = {
                        "matched_symptoms": symptom_rows,
                        "chemical_profiles": chemical_rows,
                        "chemical_count": len(
                            chemical_rows
                        ),
                    }

                    if not symptom_rows:
                        payload["warnings"].append(
                            (
                                f'No symptom rows matched the requested '
                                f'outcome "{outcome}".'
                            )
                        )
                    elif not chemical_rows:
                        payload["warnings"].append(
                            (
                                f'No chemical outcome rows were found '
                                f'for "{outcome}".'
                            )
                        )

    except KushwellDataError:
        raise

    except Exception as exc:
        raise KushwellDataError(
            f"Live Kushwell database query failed: {exc}"
        ) from exc

    return payload