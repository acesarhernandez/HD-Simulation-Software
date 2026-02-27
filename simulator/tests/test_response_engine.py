from helpdesk_sim.services.response_engine import RuleBasedResponseEngine


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
