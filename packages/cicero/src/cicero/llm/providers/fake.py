from typing import Dict, Any, Optional

class FakeLLMProvider:
    """Scripted LLM provider for 100ms deterministic CI unit tests."""
    def __init__(self, responses: Optional[Dict[str, str]] = None):
        self.responses = responses or {}
        self.call_history = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.call_history.append({"prompt": prompt, "kwargs": kwargs})
        for key, canned in self.responses.items():
            if key in prompt:
                return canned
        return '{"result": "mock_response", "status": "success"}'
