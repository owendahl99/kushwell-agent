from core.strain_research import StrainResearchEngine


class _FakeClient:
    pass


def test_default_strain_research_output_budget(monkeypatch):
    monkeypatch.delenv("OPENAI_STRAIN_RESEARCH_MAX_OUTPUT_TOKENS", raising=False)

    engine = StrainResearchEngine(client=_FakeClient(), model="gpt-test")

    assert engine.max_output_tokens == 6000


def test_strain_research_output_budget_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("OPENAI_STRAIN_RESEARCH_MAX_OUTPUT_TOKENS", "9000")
    assert (
        StrainResearchEngine(client=_FakeClient(), model="gpt-test").max_output_tokens
        == 9000
    )

    monkeypatch.setenv("OPENAI_STRAIN_RESEARCH_MAX_OUTPUT_TOKENS", "99999")
    assert (
        StrainResearchEngine(client=_FakeClient(), model="gpt-test").max_output_tokens
        == 12000
    )

    monkeypatch.setenv("OPENAI_STRAIN_RESEARCH_MAX_OUTPUT_TOKENS", "invalid")
    assert (
        StrainResearchEngine(client=_FakeClient(), model="gpt-test").max_output_tokens
        == 6000
    )
