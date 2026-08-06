from __future__ import annotations

from types import SimpleNamespace

from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner
from core.strain_research import (
    FLOWER_THC_MAX_PERCENT,
    StrainResearchEngine,
)
from core.tool_registry import registry


def test_parser_classifies_strain_research_before_recommendation():
    request = semantic_parser.parse(
        'Research everything missing for this strain "Zkittlez" review 17'
    )

    assert request["action"] == "research_strain"
    assert request["subject"] == "strain_identity"
    assert request["constraints"]["candidate_name"] == "Zkittlez"
    assert request["constraints"]["review_id"] == 17
    assert request["constraints"]["auto_promote"] is False
    assert request["constraints"]["operations"] == ["research_strain"]


def test_planner_builds_only_the_governed_strain_research_node():
    request = semantic_parser.parse('Research strain "Zkittlez"')
    graph = semantic_planner.plan(request)

    assert [node["tool"] for node in graph["nodes"]] == ["research_strain"]
    assert graph["nodes"][0]["args"]["candidate_name"] == "Zkittlez"
    assert "query_recommendations" not in {
        node["tool"] for node in graph["nodes"]
    }


def test_tool_registry_contains_first_class_strain_research():
    tool = registry.get("research_strain")

    assert tool.required_args == ["candidate_name"]
    assert "research.read" in tool.permissions


class _FakeResponses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.responses = _FakeResponses(response)


def _response_for(text: str):
    return SimpleNamespace(
        output_text=text,
        model_dump=lambda: {
            "id": "resp_test",
            "status": "completed",
            "model": "gpt-test",
            "output_text": text,
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.org/zkittlez",
                                    "title": "Official Zkittlez Genetics",
                                    "start_index": 0,
                                    "end_index": len(text),
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )


def test_engine_returns_source_attributed_flower_only_finding():
    text = (
        "BREEDER / ORIGIN\n"
        "Original breeder: 3rd Gen Family Farm.\n"
        "LINEAGE / PARENTS\n"
        "Parents: Grape Ape x Grapefruit.\n"
        "FLOWER CHEMISTRY\n"
        "Cultivar flower THC range: 15-23%. "
        "Dominant terpenes: caryophyllene and humulene."
    )
    client = _FakeClient(_response_for(text))
    engine = StrainResearchEngine(client=client, model="gpt-test")

    result = engine.research({"candidate_name": "Zkittlez"})

    assert result["action"] == "research_strain"
    assert result["auto_promote"] is False
    assert result["breeders"] == ["3rd Gen Family Farm"]
    assert result["parents"] == ["Grape Ape", "Grapefruit"]
    assert result["dominant_terpenes"] == ["caryophyllene", "humulene"]
    assert result["findings"][0]["source_url"] == "https://example.org/zkittlez"
    assert result["findings"][0]["thc_range"] == {
        "min": 15.0,
        "max": 23.0,
        "mean": 19.0,
    }
    assert client.responses.kwargs["tool_choice"] == "required"
    assert client.responses.kwargs["store"] is False


def test_engine_rejects_implausible_retail_potency_as_flower_baseline():
    text = (
        "FLOWER CHEMISTRY\n"
        "A retail listing reports strain flower THC 93.87%. "
        "Another package total displays 1000% THC."
    )
    engine = StrainResearchEngine(
        client=_FakeClient(_response_for(text)),
        model="gpt-test",
    )

    result = engine.research({"candidate_name": "Example Strain"})

    assert FLOWER_THC_MAX_PERCENT == 40.0
    assert result["findings"][0]["thc_range"] == {}
    assert any("THC range" in gap for gap in result["gaps"])


def test_prompt_excludes_product_forms_and_recommendations():
    prompt = StrainResearchEngine.prompt(
        "Zkittlez",
        StrainResearchEngine.default_queries("Zkittlez"),
    ).lower()

    for term in (
        "concentrate",
        "vape",
        "edible",
        "preroll",
        "retail product potency",
        "not a recommendation",
        "never approve",
    ):
        assert term in prompt
