from app.api.projects._intent import _is_execute_now_intent


def test_exact_trigger_phrases_match():
    assert _is_execute_now_intent("go ahead")
    assert _is_execute_now_intent("let's go")
    assert _is_execute_now_intent("run it")


def test_natural_sentences_wrapping_trigger_phrases_match():
    assert _is_execute_now_intent("Run this now")
    assert _is_execute_now_intent("Go ahead make the deliverable now")
    assert _is_execute_now_intent("Lets go with designed consolidation")


def test_questions_and_hedging_do_not_match():
    assert not _is_execute_now_intent("should we go ahead with this?")
    assert not _is_execute_now_intent("what if we go ahead with a different approach")
    assert not _is_execute_now_intent("I am not sure, can you explain what go ahead means")


def test_unrelated_messages_do_not_match():
    assert not _is_execute_now_intent("thanks")
    assert not _is_execute_now_intent("hello")
    assert not _is_execute_now_intent("")
