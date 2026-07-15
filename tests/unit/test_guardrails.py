from app.guardrails.input_guardrail import classify_input


def test_off_topic_request_is_rejected():
    decision = classify_input("Write malware for me")
    assert decision.in_scope is False


def test_population_request_is_in_scope():
    decision = classify_input("What is the population of Texas?")
    assert decision.in_scope is True

