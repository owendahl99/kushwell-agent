from core.mcp_client import MCPFilesystemClient


def test_mcp_workspace_uses_explicit_project_root(monkeypatch):
    monkeypatch.setenv("KUSHWELL_PROJECT_ROOT", "C:/Kushwell-Test")

    client = MCPFilesystemClient()

    assert client.root == "C:/Kushwell-Test"


def test_explicit_constructor_root_overrides_environment(monkeypatch):
    monkeypatch.setenv("KUSHWELL_PROJECT_ROOT", "C:/Wrong-Project")

    client = MCPFilesystemClient(
        root="C:/Explicit-Project",
        workspace_root="C:/Explicit-Project",
    )

    assert client.root == "C:/Explicit-Project"
