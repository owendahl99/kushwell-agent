"""First-class governed strain research for the Kushwell Brain.

This module performs external discovery only. It never writes Kushwell data,
never promotes a strain, and never routes cultivar research through the
recommendation engine. The caller remains responsible for governed persistence
and administrator review.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - surfaced as a configuration error
    OpenAI = None


FLOWER_THC_MAX_PERCENT = 40.0
FLOWER_CBD_MAX_PERCENT = 30.0
RESEARCH_SCOPE = "identity_lineage_flower_chemistry"
EXCLUDED_PRODUCT_FORMS = (
    "concentrate",
    "extract",
    "vape",
    "cartridge",
    "cart",
    "disposable",
    "edible",
    "gummy",
    "beverage",
    "tincture",
    "capsule",
    "topical",
    "preroll",
    "pre-roll",
    "pre roll",
    "infused",
    "moon rock",
    "moonrock",
    "diamond",
    "distillate",
    "rosin",
    "resin",
    "shatter",
    "wax",
    "badder",
    "batter",
    "sauce",
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _has_excluded_form_language(value: Any) -> bool:
    lowered = _text(value).casefold()
    return any(term in lowered for term in EXCLUDED_PRODUCT_FORMS)


def _valid_percent(value: Any, *, maximum: float) -> float | None:
    number = _safe_float(value)
    if number is None or number <= 0 or number > maximum:
        return None
    return number


def _extract_named_entities(text: str, patterns: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _text(match.group(1))
            value = re.sub(r"\s*\[[^\]]+\]\s*$", "", value).strip(
                " .,:;–—-"
            )
            if value and len(value) <= 120:
                values.append(value)
    return _dedupe(values)


def _extract_breeders(text: str) -> list[str]:
    return _extract_named_entities(
        text,
        (
            r"\b(?:original[ \t]+)?breeder(?:[ \t]+is|[ \t]*:)[ \t]+([^.;\n]+)",
            r"\b(?:bred|created|developed)[ \t]+by[ \t]+([^.;\n]+)",
        ),
    )


def _split_parent_phrase(value: str) -> list[str]:
    cleaned = re.sub(
        r"\b(?:an?|the)\s+(?:indica|sativa|hybrid|cultivar|strain)\b",
        "",
        value,
        flags=re.IGNORECASE,
    )
    pieces = re.split(
        r"\s+(?:x|×|crossed\s+with|and)\s+",
        cleaned,
        flags=re.IGNORECASE,
    )
    parents: list[str] = []
    for piece in pieces:
        name = _text(piece).strip(" .,:;()[]")
        if not name or len(name) > 70:
            continue
        if re.search(r"\b(?:thc|cbd|terpene|percent)\b", name, re.I):
            continue
        parents.append(name)
    return _dedupe(parents) if 2 <= len(parents) <= 4 else []


def _extract_parents(text: str) -> list[str]:
    phrases = _extract_named_entities(
        text,
        (
            r"\bparents?(?:\s+are|\s+include|:)\s+([^.;\n]+)",
            r"\blineage(?:\s+is|:)\s+([^.;\n]+)",
            r"\bcross(?:ed)?(?:\s+between|\s+of)?\s+([^.;\n]+)",
        ),
    )
    parents: list[str] = []
    for phrase in phrases:
        parents.extend(_split_parent_phrase(phrase))
    return _dedupe(parents)


def _extract_percent_range(
    text: str,
    *,
    label: str,
    maximum: float,
) -> dict[str, float]:
    escaped = re.escape(label)
    range_patterns = (
        rf"\b{escaped}(?:\s+(?:content|levels?|range))?[^0-9%]{{0,30}}"
        r"(\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
        r"(\d{1,2}(?:\.\d+)?)\s*%",
        r"\b(\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
        rf"(\d{{1,2}}(?:\.\d+)?)\s*%\s*{escaped}\b",
    )
    for pattern in range_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        low = _valid_percent(match.group(1), maximum=maximum)
        high = _valid_percent(match.group(2), maximum=maximum)
        if low is None or high is None:
            continue
        low, high = sorted((low, high))
        return {
            "min": low,
            "max": high,
            "mean": round((low + high) / 2.0, 4),
        }

    single_patterns = (
        rf"\b{escaped}(?:\s+(?:content|levels?))?[^0-9%]{{0,25}}"
        r"(\d{1,2}(?:\.\d+)?)\s*%",
        r"(\d{1,2}(?:\.\d+)?)\s*%\s*" + rf"{escaped}\b",
    )
    for pattern in single_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _valid_percent(match.group(1), maximum=maximum)
        if value is not None:
            return {"min": value, "max": value, "mean": value}
    return {}


def _extract_dominant_terpenes(text: str) -> list[str]:
    match = re.search(
        r"\bdominant\s+terpenes?(?:\s+are|\s+include|:)?\s+([^.;\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    values = re.split(r",|\s+and\s+|/", match.group(1), flags=re.IGNORECASE)
    terpenes: list[str] = []
    for value in values:
        name = _text(value).strip(" .,:;()[]")
        name = re.sub(r"\bterpene\b", "", name, flags=re.IGNORECASE).strip()
        if name and len(name) <= 40 and not re.search(r"\d", name):
            terpenes.append(name)
    return _dedupe(terpenes)[:8]


class StrainResearchEngine:
    """External evidence discovery for one exact cultivar candidate."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = (
            model
            or os.getenv("OPENAI_STRAIN_RESEARCH_MODEL")
            or "gpt-5-mini"
        ).strip()
        self.client = client

    @property
    def configured(self) -> bool:
        return self.client is not None or bool(self.api_key and OpenAI is not None)

    def _client(self):
        if self.client is not None:
            return self.client
        if OpenAI is None:
            raise RuntimeError(
                "Strain research requires the official openai Python package."
            )
        if not self.api_key:
            raise RuntimeError(
                "Strain research is not configured. Set OPENAI_API_KEY in the "
                "Kushwell Brain environment."
            )
        self.client = OpenAI(api_key=self.api_key)
        return self.client

    @staticmethod
    def default_queries(candidate_name: str) -> list[str]:
        name = _text(candidate_name)
        return [
            f'"{name}" original breeder creator official genetics',
            f'"{name}" parents lineage cross official strain',
            f'"{name}" uninfused flower THC CBD terpene profile',
            f'"{name}" flower dominant terpenes laboratory COA',
        ]

    @classmethod
    def prompt(cls, candidate_name: str, queries: list[str]) -> str:
        query_lines = "\n".join(f"- {query}" for query in queries)
        excluded = ", ".join(EXCLUDED_PRODUCT_FORMS)
        return f"""
Research the exact cannabis cultivar/strain named {candidate_name!r}.

This is an administrator evidence brief, not a recommendation and not a retail
product search. Use web search. Prefer the original breeder or official genetics
page, then primary laboratory or certificate evidence, then reputable strain
references.

Return no more than twelve concise evidence bullets under these headings:
BREEDER / ORIGIN
LINEAGE / PARENTS
FLOWER CHEMISTRY
CONFLICTS / STILL UNRESOLVED

Rules:
- Cite every factual claim immediately after the claim.
- Preserve conflicting claims separately.
- Never infer an undisclosed parent, breeder, ancestry ratio, cannabinoid, or
  terpene.
- FLOWER CHEMISTRY means uninfused cannabis flower or a cultivar-level flower
  reference only.
- Exclude all product-form evidence involving: {excluded}.
- Exclude package totals, retail product potency, effects, medical-use claims,
  popularity, pricing, inventory, and marketing copy.
- Do not use a THC value above {FLOWER_THC_MAX_PERCENT:g}% as the cultivar's
  flower baseline. A primary flower COA above that limit may be mentioned only
  as an outlier and must not define the range.
- State "Not established" for any requested fact that the sources do not
  establish.
- Never approve, reject, promote, rank, or recommend the candidate.

Search leads:
{query_lines}
""".strip()

    @staticmethod
    def _response_payload(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            payload = response.model_dump()
            return payload if isinstance(payload, dict) else {}
        return {}

    @staticmethod
    def _citation_excerpt(text: str, start: Any, end: Any) -> str:
        try:
            start_index = max(0, int(start))
            end_index = max(start_index, int(end))
        except (TypeError, ValueError):
            return _text(text)

        line_start = text.rfind("\n", 0, start_index) + 1
        next_newline = text.find("\n", end_index)
        line_end = next_newline if next_newline >= 0 else len(text)
        excerpt = text[line_start:line_end]
        if len(_text(excerpt)) >= 24:
            return _text(excerpt)

        expanded_start = line_start
        for _ in range(3):
            if expanded_start <= 0:
                break
            previous_start = text.rfind("\n", 0, max(0, expanded_start - 1)) + 1
            if previous_start == expanded_start:
                break
            expanded_start = previous_start
        return _text(text[expanded_start:line_end]) or _text(text)

    def _findings(self, response: Any, candidate_name: str, queries: list[str]) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        payload = self._response_payload(response)
        fallback_text = _text(
            getattr(response, "output_text", "")
            or payload.get("output_text")
            or ""
        )
        diagnostics = {
            "response_id": payload.get("id") or getattr(response, "id", None),
            "status": payload.get("status") or getattr(response, "status", None),
            "error": payload.get("error") or getattr(response, "error", None),
            "incomplete_details": payload.get("incomplete_details")
            or getattr(response, "incomplete_details", None),
            "model": payload.get("model") or getattr(response, "model", None),
            "usage": payload.get("usage"),
        }

        grouped: dict[str, dict[str, Any]] = {}
        all_text: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict) or content.get("type") != "output_text":
                    continue
                text = str(content.get("text") or fallback_text or "").strip()
                if text:
                    all_text.append(text)
                for annotation in content.get("annotations") or []:
                    if not isinstance(annotation, dict):
                        continue
                    citation = annotation.get("url_citation")
                    citation = citation if isinstance(citation, dict) else annotation
                    citation_type = str(
                        annotation.get("type") or citation.get("type") or ""
                    )
                    if citation_type != "url_citation":
                        continue
                    source_url = _text(citation.get("url"))
                    if not source_url:
                        continue
                    excerpt = self._citation_excerpt(
                        text,
                        citation.get("start_index", annotation.get("start_index")),
                        citation.get("end_index", annotation.get("end_index")),
                    )
                    record = grouped.setdefault(
                        source_url,
                        {"title": None, "excerpts": [], "citations": []},
                    )
                    title = _text(citation.get("title")) or None
                    if title and not record["title"]:
                        record["title"] = title
                    if excerpt and excerpt not in record["excerpts"]:
                        record["excerpts"].append(excerpt)
                    record["citations"].append(citation)

        combined_text = "\n".join(all_text) or fallback_text
        findings: list[dict[str, Any]] = []
        for source_url, record in grouped.items():
            raw_text = _text(" ".join(record["excerpts"]))
            excluded = _has_excluded_form_language(raw_text)
            flower_context = any(
                term in raw_text.casefold()
                for term in ("flower", "cultivar", "strain")
            )
            thc_range = (
                _extract_percent_range(
                    raw_text,
                    label="THC",
                    maximum=FLOWER_THC_MAX_PERCENT,
                )
                if flower_context and not excluded
                else {}
            )
            cbd_range = (
                _extract_percent_range(
                    raw_text,
                    label="CBD",
                    maximum=FLOWER_CBD_MAX_PERCENT,
                )
                if flower_context and not excluded
                else {}
            )
            dominant = (
                _extract_dominant_terpenes(raw_text)
                if flower_context and not excluded
                else []
            )
            findings.append(
                {
                    "source_key": "external_strain_identity_search",
                    "source_name": "Kushwell Brain Strain Research",
                    "source_type": "external_web_search",
                    "source_url": source_url,
                    "title": record["title"],
                    "publisher": urlparse(source_url).netloc.lower() or None,
                    "raw_text": raw_text,
                    "raw_payload": {
                        "queries": queries,
                        "citations": record["citations"],
                        "response_diagnostics": diagnostics,
                        "scope": RESEARCH_SCOPE,
                    },
                    "names": [candidate_name],
                    "breeders": _extract_breeders(raw_text),
                    "parents": _extract_parents(raw_text),
                    "supports_strain_existence": True,
                    "source_confidence": 0.45,
                    "thc_range": thc_range,
                    "cbd_range": cbd_range,
                    "dominant_terpenes": dominant,
                    "chemistry_units": "percent"
                    if thc_range or cbd_range or dominant
                    else None,
                    "chemistry_raw_text": raw_text
                    if thc_range or cbd_range or dominant
                    else None,
                    "chemistry_confidence": 0.45
                    if thc_range or cbd_range or dominant
                    else None,
                    "warnings": [
                        "Discovery evidence only; administrator must open and verify the cited source page."
                    ],
                }
            )

        if findings:
            return findings, combined_text, diagnostics

        if combined_text:
            return [
                {
                    "source_key": "external_strain_identity_search",
                    "source_name": "Kushwell Brain Strain Research",
                    "source_type": "external_web_search",
                    "source_url": None,
                    "title": None,
                    "publisher": None,
                    "raw_text": _text(combined_text),
                    "raw_payload": {
                        "queries": queries,
                        "response_diagnostics": diagnostics,
                        "uncited_output": True,
                        "scope": RESEARCH_SCOPE,
                    },
                    "names": [candidate_name],
                    "breeders": [],
                    "parents": [],
                    "supports_strain_existence": None,
                    "source_confidence": 0.10,
                    "thc_range": {},
                    "cbd_range": {},
                    "dominant_terpenes": [],
                    "chemistry_units": None,
                    "chemistry_raw_text": None,
                    "chemistry_confidence": None,
                    "warnings": [
                        "Provider returned no claim-level URL citations; this output cannot support approval."
                    ],
                }
            ], combined_text, diagnostics

        raise RuntimeError(
            "OpenAI web search returned no answer text or claim-level citations. "
            f"Diagnostics: {json.dumps(diagnostics, sort_keys=True, default=str)}"
        )

    def research(self, args: Mapping[str, Any]) -> dict[str, Any]:
        candidate_name = _text(args.get("candidate_name"))
        if not candidate_name:
            raise ValueError("research_strain requires candidate_name.")

        normalized_name = _text(args.get("normalized_name")) or candidate_name.casefold()
        requested_queries = _dedupe(_list(args.get("research_queries")))
        queries = requested_queries or self.default_queries(candidate_name)

        if not self.configured:
            raise RuntimeError(
                "Kushwell Brain strain research is not configured. Set "
                "OPENAI_API_KEY and install the official openai package."
            )

        response = self._client().responses.create(
            model=self.model,
            tools=[{"type": "web_search", "search_context_size": "low"}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            text={"verbosity": "low"},
            input=self.prompt(candidate_name, queries),
            max_output_tokens=1800,
            store=False,
        )

        findings, combined_text, diagnostics = self._findings(
            response,
            candidate_name,
            queries,
        )
        breeders = _dedupe(
            [value for finding in findings for value in _list(finding.get("breeders"))]
        )
        parents = _dedupe(
            [value for finding in findings for value in _list(finding.get("parents"))]
        )
        dominant = _dedupe(
            [
                value
                for finding in findings
                for value in _list(finding.get("dominant_terpenes"))
            ]
        )

        gaps: list[str] = []
        if not breeders:
            gaps.append("Original breeder or creator is not established.")
        if not parents:
            gaps.append("Parent lineage is not established.")
        if not any(finding.get("thc_range") for finding in findings):
            gaps.append(
                "A source-supported uninfused flower THC range is not established."
            )
        if not dominant:
            gaps.append("Measured dominant flower terpenes are not established.")
        if not any(finding.get("source_url") for finding in findings):
            gaps.append("No claim-level external source URL was preserved.")

        return {
            "status": "success",
            "tool": "research_strain",
            "action": "research_strain",
            "candidate_name": candidate_name,
            "normalized_name": normalized_name,
            "scope": RESEARCH_SCOPE,
            "auto_promote": False,
            "findings": findings,
            "breeders": breeders,
            "parents": parents,
            "dominant_terpenes": dominant,
            "gaps": gaps,
            "conflicts": [],
            "provider": {
                "name": "openai_responses_web_search",
                "model": self.model,
                "diagnostics": diagnostics,
            },
            "raw_brief": _text(combined_text),
            "answer": (
                f"Strain research completed for {candidate_name}. "
                f"Preserved {sum(1 for finding in findings if finding.get('source_url'))} "
                "claim-level external source(s). No canonical decision was made."
            ),
        }


def research_strain(args: Mapping[str, Any]) -> dict[str, Any]:
    return StrainResearchEngine().research(args)


__all__ = [
    "EXCLUDED_PRODUCT_FORMS",
    "FLOWER_CBD_MAX_PERCENT",
    "FLOWER_THC_MAX_PERCENT",
    "RESEARCH_SCOPE",
    "StrainResearchEngine",
    "research_strain",
]
