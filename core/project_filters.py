from pathlib import Path


TEXT_EXTENSIONS = {
    ".py",
    ".html",
    ".jinja",
    ".jinja2",
    ".js",
    ".ts",
    ".css",
    ".scss",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
}


IGNORED_EXTENSIONS = {
    ".lnk",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyd",
}


IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}


def should_read(path: str) -> bool:

    p = Path(path)

    if any(part in IGNORED_DIRECTORIES for part in p.parts):
        return False

    ext = p.suffix.lower()

    if ext in IGNORED_EXTENSIONS:
        return False

    return ext in TEXT_EXTENSIONS