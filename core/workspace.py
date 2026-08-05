"""
core/workspace.py

Workspace management for the Kushwell Brain.

The rest of the system should NEVER work directly with Windows
paths. Everything should use workspace:/ URIs.

Examples
--------
workspace:/router.py
workspace:/templates/index.html
workspace:/logs/brain.log
workspace:/projects/demo/main.py
"""

from __future__ import annotations

from pathlib import Path


class WorkspaceError(Exception):
    """Raised when a workspace path cannot be resolved."""
    pass


class WorkspaceManager:
    """
    Central workspace manager.

    Responsible for translating virtual workspace paths into
    real filesystem paths.

    The agent should ONLY ever use workspace:/ paths.
    """

    def __init__(self, root: str | Path):

        self.root = Path(root).resolve()

    # ---------------------------------------------------------
    # Resolve workspace:/...  -> absolute filesystem path
    # ---------------------------------------------------------

    def resolve(self, workspace_path: str) -> str:

        if not isinstance(workspace_path, str):
            raise WorkspaceError("Workspace path must be a string.")

        if not workspace_path.startswith("workspace:/"):
            raise WorkspaceError(
                f"Invalid workspace path: {workspace_path}"
            )

        relative = workspace_path[len("workspace:/"):]

        resolved = (self.root / relative).resolve()

        # Prevent escaping outside the workspace root
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise WorkspaceError(
                f"Access outside workspace is not allowed: {workspace_path}"
            )

        return str(resolved)

    # ---------------------------------------------------------
    # Convert absolute path back into workspace:/...
    # ---------------------------------------------------------

    def to_workspace(self, filesystem_path: str | Path) -> str:

        filesystem_path = Path(filesystem_path).resolve()

        try:
            relative = filesystem_path.relative_to(self.root)
        except ValueError:
            raise WorkspaceError(
                f"{filesystem_path} is outside the workspace."
            )

        return f"workspace:/{relative.as_posix()}"

    # ---------------------------------------------------------
    # Root path
    # ---------------------------------------------------------

    @property
    def workspace_root(self) -> str:
        return str(self.root)

    # ---------------------------------------------------------
    # Exists?
    # ---------------------------------------------------------

    def exists(self, workspace_path: str) -> bool:

        return Path(self.resolve(workspace_path)).exists()

    # ---------------------------------------------------------
    # Is directory?
    # ---------------------------------------------------------

    def is_dir(self, workspace_path: str) -> bool:

        return Path(self.resolve(workspace_path)).is_dir()

    # ---------------------------------------------------------
    # Is file?
    # ---------------------------------------------------------

    def is_file(self, workspace_path: str) -> bool:

        return Path(self.resolve(workspace_path)).is_file()

    # ---------------------------------------------------------
    # Create directory
    # ---------------------------------------------------------

    def mkdir(
        self,
        workspace_path: str,
        parents: bool = True,
        exist_ok: bool = True,
    ):

        Path(self.resolve(workspace_path)).mkdir(
            parents=parents,
            exist_ok=exist_ok,
        )

    # ---------------------------------------------------------
    # List directory
    # ---------------------------------------------------------

    def listdir(self, workspace_path: str):

        path = Path(self.resolve(workspace_path))

        return sorted(
            item.name
            for item in path.iterdir()
        )

    # ---------------------------------------------------------
    # Read text
    # ---------------------------------------------------------

    def read_text(
        self,
        workspace_path: str,
        encoding: str = "utf-8",
    ) -> str:

        return Path(
            self.resolve(workspace_path)
        ).read_text(
            encoding=encoding
        )

    # ---------------------------------------------------------
    # Write text
    # ---------------------------------------------------------

    def write_text(
        self,
        workspace_path: str,
        text: str,
        encoding: str = "utf-8",
    ):

        path = Path(self.resolve(workspace_path))

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            text,
            encoding=encoding,
        )