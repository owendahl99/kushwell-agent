from core.intents.intent_types import IntentDefinition


class IntentRegistry:
    def __init__(self):
        self._intents: list[IntentDefinition] = []

    def register(self, intent: IntentDefinition):
        self._intents.append(intent)

    def all(self):
        return sorted(
            self._intents,
            key=lambda i: i.priority,
            reverse=True,
        )


intent_registry = IntentRegistry()