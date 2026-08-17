"""Gate 1 conformance journey for every supported ingress.

The driver must wrap the real interface under test: a CLI subprocess, a live
HTTP socket, or an MCP stdio subprocess.  In-process harness calls are not a
valid substitute for any of those interfaces.
"""

from __future__ import annotations

from typing import Any, Protocol


class JourneyDriver(Protocol):
    """The black-box operations required by the Gate 1 journey."""

    name: str

    def new_domain(self, goal: str) -> dict[str, Any]: ...

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]: ...

    def activate_pack(self, name: str) -> dict[str, Any]: ...

    def capture(self, text: str) -> dict[str, Any]: ...

    def query(self, *, domain: str | None = None, limit: int = 50) -> list[dict[str, Any]]: ...

    def correct(
        self,
        *,
        text: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        target_domain: str | None = None,
    ) -> dict[str, Any]: ...

    def review_list(self) -> list[dict[str, Any]]: ...

    def review_resolve(self, approval_id: str, decision: str) -> dict[str, Any]: ...

    def export(self, *, domain: str | None = None) -> dict[str, Any]: ...

    def restart(self) -> None: ...


CAPTURE_TEXT = "baked a 75% hydration country loaf, came out great"
CORRECTION_TEXT = "actually the hydration was 80 not 75"


def run_journey(driver: JourneyDriver) -> None:
    """Run the concrete create → activate → capture → export journey."""

    # 1. CREATE — atlas browse, then skip to compile a working pack.
    turn = driver.new_domain("track my bouldering climbing sessions")
    assert turn["state"] == "fork", turn
    done = driver.wizard_reply(turn["session_id"], "skip")
    assert done["state"] in {"test_drive", "repair"}, done
    assert done["domain"] or done.get("pack", {}).get("name"), done

    # 2. ACTIVATE — use a curated bundled pack for deterministic routing.
    activated = driver.activate_pack("sourdough")
    assert activated["name"] == "sourdough", activated

    # 3. CAPTURE
    receipt = driver.capture(CAPTURE_TEXT)
    assert receipt["status"] == "applied", receipt
    assert any(span["domain"] == "sourdough" for span in receipt["routed"]), receipt

    # 4. QUERY
    rows = driver.query(domain="sourdough")
    assert rows, "query returned nothing"
    assert any("country loaf" in (row.get("raw_text") or "") for row in rows)

    # 5. CORRECT — one-message natural-language correction against the fresh object.
    corrected = driver.correct(text=CORRECTION_TEXT)
    assert corrected.get("applied") is True, corrected

    # 6. REVIEW — resolve anything pending so the queue has a concrete postcondition.
    items = driver.review_list()
    for item in items:
        approval_id = item.get("approval_id") or item.get("id")
        assert approval_id, item
        result = driver.review_resolve(str(approval_id), "approved")
        assert result.get("error") in (None, ""), result
    assert driver.review_list() == []

    # 7. EXPORT — the correction must be visible in canonical data ownership output.
    dump = driver.export(domain="sourdough")
    assert dump["format"] == "domain-foundry-export/1", dump
    bakes = dump["domains"]["sourdough"]["objects"]["bake"]
    assert bakes, "export contains no bakes"
    assert any(
        float(bake["fields"].get("hydration") or 0) == 80.0 for bake in bakes
    ), "corrected hydration (80) missing from export"

    # 8. RESTART — a new process must see exactly the same durable state.
    driver.restart()
    rows_after_restart = driver.query(domain="sourdough")
    assert len(rows_after_restart) >= len(rows), "data lost across restart"
    dump_after_restart = driver.export(domain="sourdough")
    assert dump_after_restart["counts"] == dump["counts"], (
        "export changed across restart",
        dump,
        dump_after_restart,
    )
