from __future__ import annotations

from typing import Any

from core.intents.intent_registry import intent_registry

# Load intent packs
import core.intents.filesystem  # noqa
import core.intents.templates  # noqa


class IntentParser:
    def parse(self, user_input: str) -> dict[str, Any]:
        text = (user_input or "").strip()
        t = text.lower()

        best = None
        best_score = 0

        for intent in intent_registry.all():
            score = self._score(intent, t)

            if score > best_score:
                best = intent
                best_score = score

        if not best:
            return {
                "intent": "list_directory",
                "target": "workspace:/",
                "confidence": 0,
                "requires_confirmation": False,
                "original_request": text,
            }

        return {
            "intent": best.name,
            "target": self._detect_target(best, t),
            "confidence": best_score,
            "requires_confirmation": best.requires_confirmation,
            "original_request": text,
        }

    def _score(self, intent, text: str) -> int:
        score = intent.priority

        for keyword in intent.keywords:
            if keyword in text:
                score += 10

        for example in intent.examples:
            if example in text:
                score += 25

        return score

    def _detect_target(self, intent, text: str) -> str:
        for hint, target in intent.target_hints.items():
            if hint in text:
                return target

        return "workspace:/"


intent_parser = IntentParser()