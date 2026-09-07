from flynn_agents_sdk import ContextCompiler, ContextItem


def test_context_prioritizes_whole_items_and_discloses_omissions():
    result = ContextCompiler(max_characters=20).compile(
        (
            ContextItem("history", "too much text to fit", 0, ("old",)),
            ContextItem("now", "frame", 10, ("t1",)),
        )
    )
    assert result.included_ids == ("now",)
    assert result.omitted_ids == ("history",)
    assert result.evidence_ids == ("t1",)
    assert len(result.text) <= 20
