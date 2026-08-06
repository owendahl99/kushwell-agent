import agent as agent_module
from agent import (
    DEFAULT_STRAIN_RESEARCH_TIMEOUT,
    STRAIN_RESEARCH_TIMEOUT_ENV,
    KushwellAgent,
    _bounded_strain_research_timeout,
)


def _build_agent(monkeypatch):
    monkeypatch.setattr(agent_module, "MCPFilesystemClient", lambda: object())
    monkeypatch.setattr(agent_module, "GPTRouterV8", lambda: object())
    monkeypatch.setattr(agent_module, "MemoryStore", lambda: object())
    return KushwellAgent()


def test_typed_research_has_a_dedicated_five_minute_executor(monkeypatch):
    monkeypatch.delenv(STRAIN_RESEARCH_TIMEOUT_ENV, raising=False)

    agent = _build_agent(monkeypatch)

    assert agent.executor.config.task_timeout == 60.0
    assert agent.executor.config.max_retries == 2
    assert agent.strain_research_timeout == DEFAULT_STRAIN_RESEARCH_TIMEOUT
    assert agent.strain_research_executor.config.task_timeout == 300.0
    assert agent.strain_research_executor.config.max_retries == 0
    assert agent.strain_research_executor.config.max_parallel_tasks == 1


def test_typed_research_timeout_environment_is_safely_bounded(monkeypatch):
    monkeypatch.setenv(STRAIN_RESEARCH_TIMEOUT_ENV, "5")
    assert _bounded_strain_research_timeout() == 120.0

    monkeypatch.setenv(STRAIN_RESEARCH_TIMEOUT_ENV, "5000")
    assert _bounded_strain_research_timeout() == 900.0

    monkeypatch.setenv(STRAIN_RESEARCH_TIMEOUT_ENV, "not-a-number")
    assert _bounded_strain_research_timeout() == 300.0


def test_blank_typed_research_failure_gets_a_visible_diagnostic():
    agent = KushwellAgent.__new__(KushwellAgent)
    agent.strain_research_timeout = 300.0
    execution_result = {
        "results": {
            "strain_research": {
                "status": "failed",
                "error": "",
            }
        },
        "errors": {
            "strain_research": {
                "status": "failed",
                "error": "",
            }
        },
    }

    agent._normalize_strain_research_failure(execution_result)

    for collection in ("results", "errors"):
        message = execution_result[collection]["strain_research"]["error"]
        assert "failed without a provider diagnostic" in message
        assert "300 seconds" in message
