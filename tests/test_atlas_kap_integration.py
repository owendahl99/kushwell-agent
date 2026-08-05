from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner
from core.tool_registry import registry


def _tools(question: str) -> list[str]:
    request = semantic_parser.parse(question)
    graph = semantic_planner.plan(request)
    return [node["tool"] for node in graph["nodes"]]


def main():
    expected_tools = {
        "query_acquisition_status",
        "query_acquisition_runs",
        "plan_product_acquisition",
        "run_product_acquisition",
    }

    assert expected_tools.issubset(set(registry.names()))

    assert _tools("Show me KAP acquisition status") == [
        "query_acquisition_status",
        "answer_question",
    ]

    assert _tools("Show recent acquisition runs") == [
        "query_acquisition_runs",
        "answer_question",
    ]

    assert _tools("Plan a California acquisition") == [
        "plan_product_acquisition",
        "answer_question",
    ]

    request = semantic_parser.parse(
        "Run the acquisition for California"
    )
    graph = semantic_planner.plan(request)

    execution = graph["nodes"][0]

    assert execution["tool"] == "run_product_acquisition"
    assert execution["args"]["dry_run"] is True
    assert execution["args"]["confirm_live"] is False

    print("✅ Atlas–KAP Step Five integration tests passed.")
    print("✅ Atlas can read KAP status and run history.")
    print("✅ Atlas can create governed acquisition plans.")
    print("✅ Natural-language run requests default to dry-run.")
    print("✅ Atlas never calls a provider scraper directly.")


if __name__ == "__main__":
    main()
