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


GOAL = "i collect pokemon cards"
PICK = "a dex of the cards i own with photos"
BUILD = "build it"
CAPTURE_TEXT = "pulled a holographic Charizard from a 151 booster, NM"
CORRECTION_TEXT = "that Charizard was LP not NM"


def _is_cards_domain(name: str | None) -> bool:
    token = (name or "").lower()
    return "pokemon" in token or "card" in token


def _domain_name(turn: dict[str, Any]) -> str | None:
    return turn.get("domain") or ((turn.get("pack") or {}).get("name"))


def run_journey(driver: JourneyDriver) -> None:
    """Run create (looks + build it) → capture → correct → export."""

    # 1. CREATE — pick Card dex, wait in looks, then build it. Skip is not install.
    turn = driver.new_domain(GOAL)
    assert turn["state"] == "fork", turn
    ideas = " ".join(
        i.get("title") or ""
        for i in ((turn.get("neighborhood") or {}).get("ideas") or [])
    ).lower()
    if ideas:
        assert "card" in ideas, turn
    looks = driver.wizard_reply(turn["session_id"], PICK)
    assert looks["state"] == "looks", looks
    done = driver.wizard_reply(turn["session_id"], BUILD)
    assert done["state"] in {"test_drive", "repair"}, done
    domain = _domain_name(done)
    assert domain, done
    assert _is_cards_domain(domain), done

    # 2. CAPTURE — file a real card pull on the domain just built.
    receipt = driver.capture(CAPTURE_TEXT)
    assert receipt["status"] == "applied", receipt
    routed = [span for span in receipt["routed"] if _is_cards_domain(span.get("domain"))]
    assert routed, receipt
    routed_domain = routed[0]["domain"]

    # 3. QUERY
    rows = driver.query(domain=routed_domain)
    assert rows, "query returned nothing"
    assert any("Charizard" in (row.get("raw_text") or "") for row in rows)

    # 4. CORRECT — one-message natural-language correction against the fresh object.
    corrected = driver.correct(text=CORRECTION_TEXT)
    assert corrected.get("applied") is True, corrected

    # 5. REVIEW — resolve anything pending so the queue has a concrete postcondition.
    items = driver.review_list()
    for item in items:
        approval_id = item.get("approval_id") or item.get("id")
        assert approval_id, item
        result = driver.review_resolve(str(approval_id), "approved")
        assert result.get("error") in (None, ""), result
    assert driver.review_list() == []

    # 6. EXPORT — the correction must be visible in canonical data ownership output.
    dump = driver.export(domain=routed_domain)
    assert dump["format"] == "domain-foundry-export/1", dump
    cards = dump["domains"][routed_domain]["objects"]["card"]
    assert cards, "export contains no cards"
    assert any(
        str(card["fields"].get("notes") or "").upper() == "LP" for card in cards
    ), "corrected notes (LP) missing from export"

    # 7. RESTART — a new process must see exactly the same durable state.
    driver.restart()
    rows_after_restart = driver.query(domain=routed_domain)
    assert len(rows_after_restart) >= len(rows), "data lost across restart"
    dump_after_restart = driver.export(domain=routed_domain)
    assert dump_after_restart["counts"] == dump["counts"], (
        "export changed across restart",
        dump,
        dump_after_restart,
    )
