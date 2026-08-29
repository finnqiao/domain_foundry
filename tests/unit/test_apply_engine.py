

def test_uncoercible_number_drops_field_not_the_row(tmp_path):
    """Free text carries values like '2:1:1' into a number field. Losing one
    field is acceptable; losing the whole capture is not (product promise 2)."""
    from domain_foundry_core.api.harness import HarnessAPI
    from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage

    api = HarnessAPI(tmp_path)
    api.init()
    sess = api.new_domain("keep a coffee brewing log")
    api.wizard_reply(sess["session_id"], "just a simple log")

    class _JunkNumberLLM(LLMProvider):
        name = "fake"
        api_key = "sk-test"

        def complete_json(self, *, system, user, schema=None, model=None, tier=None):
            return CompletionResult(
                data={
                    "captures": [
                        {
                            "domain": "coffee",
                            "object_type": "brew",
                            "operation": "create",
                            "confidence": 0.95,
                            "fields": {
                                "title": "Ethiopia pourover",
                                "dose_g": "18:36:2",         # not a number
                                "brewed_at": "capture_time",  # schema default token
                                "notes": "second pour ran long",
                            },
                        }
                    ],
                    "unmatched_text": None,
                    "needs_clarification": False,
                    "clarifying_question": None,
                },
                usage=TokenUsage(input_tokens=10, output_tokens=5, model="fake", tier=tier),
            )

    api.router.llm = _JunkNumberLLM()
    api.capture("ethiopia pourover this morning, 18:36:2, second pour ran long")

    health = api.health()
    assert health.failed_change_requests == 0, "one bad field must not fail the row"

    rows = api.query(domain="coffee")
    assert len(rows) == 1 and rows[0].status == "applied"


def test_health_surfaces_failed_change_requests(tmp_path):
    """A failed change request has no approval row, so `review list` is empty.
    Health must be the place it becomes visible."""
    import sqlite3

    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(tmp_path)
    api.init()
    sess = api.new_domain("keep a coffee brewing log")
    api.wizard_reply(sess["session_id"], "just a simple log")
    api.capture("coffee log entry: ethiopia pourover")

    conn = sqlite3.connect(tmp_path / "db" / "ledger.sqlite")
    conn.execute(
        "UPDATE change_request SET status = 'failed', error = 'synthetic' WHERE id = 1"
    )
    conn.commit()
    conn.close()

    health = api.health()
    assert health.failed_change_requests == 1
    assert health.warnings and "failed to apply" in health.warnings[0]


def test_datetime_default_token_is_resolved(tmp_path):
    """A model echoing the schema's own `default: capture_time` back as a value
    must not put the literal string into a datetime column."""
    from domain_foundry_core.apply.engine import _coerce
    from domain_foundry_core.packs.models import FieldSpec

    out = _coerce(FieldSpec(type="datetime"), "capture_time")
    assert out != "capture_time"
    assert out.endswith("Z")
