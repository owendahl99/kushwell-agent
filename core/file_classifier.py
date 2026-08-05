from __future__ import annotations

from pathlib import PurePosixPath


class FileClassifier:
    """
    Determines what role a file plays in the project.

    This lets the planner choose which files are relevant
    instead of reading every source file.
    """

    DIRECTORY_TYPES = {
        "templates": "template",
        "routes": "route",
        "services": "service",
        "models": "model",
        "serializers": "serializer",
        "utils": "utility",
        "brain": "brain",
        "api": "api",
        "static": "static",
        "documentation": "documentation",
    }

    def classify(self, path: str) -> dict:
        p = PurePosixPath(path.replace("\\", "/"))

        category = "other"

        for part in p.parts:
            if part in self.DIRECTORY_TYPES:
                category = self.DIRECTORY_TYPES[part]
                break

        return {
            "path": str(p),
            "filename": p.name,
            "extension": p.suffix.lower(),
            "category": category,
            "directory": str(p.parent),
        }


file_classifier = FileClassifier()