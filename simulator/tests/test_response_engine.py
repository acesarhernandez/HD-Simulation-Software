from helpdesk_sim.services import response_engine
from helpdesk_sim.services.response_engine import OllamaResponseEngine, RuleBasedResponseEngine


def test_rule_engine_matches_username_alias() -> None:
    engine = RuleBasedResponseEngine()
    hidden_truth = {
        "clue_map": {
            "username": "My username is m.brooks",
            "error": "The message says password expired.",
        }
    }

    reply = engine.generate_reply(
        "Could you tell me which user is impacted?",
        hidden_truth,
    )
    assert "m.brooks" in reply


def test_rule_engine_password_reset_clarification() -> None:
    engine = RuleBasedResponseEngine()
    hidden_truth = {
        "ticket_type": "password_reset",
        "clue_map": {},
        "default_follow_up": "I can try steps while you stay on the ticket.",
    }

    reply = engine.generate_reply(
        "Could you clarify where you are trying to sign in?",
        hidden_truth,
    )
    assert "Windows workstation" in reply
    assert "password has expired" in reply


def test_ollama_engine_falls_back_to_rule_based_on_error(monkeypatch) -> None:
    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(response_engine.httpx, "Client", FailingClient)

    engine = OllamaResponseEngine(
        base_url="http://127.0.0.1:11434",
        model="llama3.1:8b",
        fallback_engine=RuleBasedResponseEngine(),
    )
    hidden_truth = {
        "ticket_type": "password_reset",
        "clue_map": {},
        "default_follow_up": "I can try steps while you stay on the ticket.",
    }

    reply = engine.generate_reply(
        "Could you clarify where you are trying to sign in?",
        hidden_truth,
    )
    status = engine.describe_status()

    assert "Windows workstation" in reply
    assert status["active_mode"] == "fallback_rule_based"
    assert status["fallback_reply_count"] == 1
    assert "connection refused" in str(status["last_error"])


def test_ollama_engine_returns_llm_text_when_available(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"response": "Please check the project app assignment list."}

    class WorkingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        @staticmethod
        def post(*args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(response_engine.httpx, "Client", WorkingClient)

    engine = OllamaResponseEngine(
        base_url="http://127.0.0.1:11434",
        model="llama3.1:8b",
        fallback_engine=RuleBasedResponseEngine(),
    )

    reply = engine.generate_reply("Can you tell me what the issue looks like?", {"clue_map": {}})
    status = engine.describe_status()

    assert reply == "Please check the project app assignment list."
    assert status["active_mode"] == "ollama"
    assert status["successful_llm_reply_count"] == 1
    assert status["fallback_reply_count"] == 0


def test_ollama_engine_rejects_vague_llm_output_and_falls_back(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"response": "I can try steps while you stay on the ticket."}

    class WorkingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        @staticmethod
        def post(*args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(response_engine.httpx, "Client", WorkingClient)

    engine = OllamaResponseEngine(
        base_url="http://127.0.0.1:11434",
        model="llama3.1:8b",
        fallback_engine=RuleBasedResponseEngine(),
    )
    hidden_truth = {
        "ticket_type": "password_reset",
        "clue_map": {},
        "default_follow_up": "I can try steps while you stay on the ticket.",
    }

    reply = engine.generate_reply("Where are you trying to sign in?", hidden_truth)
    status = engine.describe_status()

    assert "Windows workstation" in reply
    assert status["active_mode"] == "fallback_rule_based"
    assert status["fallback_reply_count"] == 1
    assert "vague response" in str(status["last_error"])
