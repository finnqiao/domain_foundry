"""Release-facing copy and progress for the creation journey.

The wizard engine keeps its original message field for adapters and scripts
that already depend on it.  The release surface reads ``user_message`` and
``progress`` from this module instead.  This keeps technical detail available
without making it the voice of the main journey.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

JOB_LABELS: dict[str, str] = {
    "improvement": "compare changes",
    "media_dex": "see photos",
    "lab": "try variations",
    "catalog": "browse a collection",
    "atlas": "see places",
    "event_log": "follow what happened",
    "practice": "return to your practice",
    "graph": "see connections",
    "plan": "plan ahead",
}

_JOB_PITCHES: dict[str, str] = {
    "improvement": "compare changes over time",
    "media_dex": "keep photos with each note",
    "lab": "try variations and remember what worked",
    "catalog": "keep a list you can browse",
    "atlas": "see where things happened",
    "event_log": "keep a history of what happened",
    "practice": "return to the details of your practice",
    "graph": "see how the pieces connect",
    "plan": "keep the next steps close by",
}

_FIELD_WORDS = {
    "id": "ID",
    "url": "URL",
    "abv": "ABV",
    "sac": "SAC",
    "lng": "longitude",
    "lat": "latitude",
}

# These are deliberately ordered from the most specific phrase to the most
# general word.  They apply only to the release copy field; persisted data,
# receipts, and legacy JSON keep their original vocabulary.
_COPY_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"I don't have this one catalogued, so I'll build it out of your words rather than guess\. Say one thing you'd log — exactly how you'd type it\. That becomes the first test of the app\. \(Or say 'skip'\.\)", re.I),
        "Add a note you might write on a normal day. Your words will shape the app.",
    ),
    (
        re.compile(r"And one more, a different kind of thing\. I'll hold this one back, then replay it once the app exists — so the check is honest\. \(Or say 'skip'\.\)", re.I),
        "Add a different kind of note. This one will check the app after it is built.",
    ),
    (
        re.compile(r"You skipped the examples, so this is built from your goal's keywords alone and nothing has checked it yet — log a real note and we'll see\.", re.I),
        "Built from your notes so far. Add a real note and we will see how it fits.",
    ),
    (
        re.compile(r"No second example, so nothing independent has checked this — log a real note and we'll see\.", re.I),
        "No second note yet. Add a real note and we will see how it fits.",
    ),
    (
        re.compile(r"No reasoning model is configured, so I can't research [“\"](?P<goal>.*?)[”\"] for real vocabulary and views\. You get a solid basic tracker built from your own words; add a key later and I'll rebuild it with research\.", re.I),
        "Research is not available right now. This app is built from your notes. You can add a key later to look for more patterns.",
    ),
    (
        re.compile(r"I meant to research [“\"](?P<goal>.*?)[”\"] for real vocabulary and views and couldn't: .*?\. So this is built from your own words instead, not from research\.", re.I),
        "Research is not available right now. This app is built from your notes. You can add a key later to look for more patterns.",
    ),
    (
        re.compile(r"Which of these, or say what you want it to do — a chart, photos, a mix board\. Paste a notes folder path to ingest text\. Photos: have your agent read them first, then send the text\.", re.I),
        "Choose any that fit, or describe it in your own words. You can also add notes from a local folder. Images need their text pasted here.",
    ),
    (re.compile(r"\s*\(suggested\)", re.I), " — closest to what you described"),
    (re.compile(r"chart how inputs lead to outcomes", re.I), "compare changes over time"),
    (re.compile(r"a gallery of the photos", re.I), "keep photos with each note"),
    (re.compile(r"a mix board of what worked", re.I), "try variations and remember what worked"),
    (re.compile(r"a catalog you can page through", re.I), "keep a list you can browse"),
    (re.compile(r"a map of where it happened", re.I), "see where things happened"),
    (re.compile(r"a timeline of what you logged", re.I), "keep a history of what happened"),
    (re.compile(r"a practice board you can return to", re.I), "return to the details of your practice"),
    (re.compile(r"how the pieces link", re.I), "see how the pieces connect"),
    (re.compile(r"a plan you can talk to", re.I), "keep the next steps close by"),
    (re.compile(r"held[- ]out check", re.I), "second note"),
    (re.compile(r"held[- ]out example", re.I), "second note"),
    (re.compile(r"held[- ]out phrase(?:s)?", re.I), "second note"),
    (re.compile(r"held[- ]out", re.I), "second"),
    (re.compile(r"second example", re.I), "second note"),
    (re.compile(r"evidence tier", re.I), "based on"),
    (re.compile(r"routing passed", re.I), "went to the right place"),
    (re.compile(r"filed into", re.I), "went to the right place: "),
    (re.compile(r"didn't file; it goes to the unfiled card for review\. Tell me what it should be and I'll learn it\.", re.I), "did not go to the right place yet. Your note is safe to review; tell me where it belongs and I will adjust it."),
    (re.compile(r"personal draft", re.I), "built from your notes"),
    (re.compile(r"building the exact app", re.I), "putting your app together"),
    (re.compile(r"AI recommended", re.I), "closest to what you described"),
    (re.compile(r"LLM-designed", re.I), "researched"),
    (re.compile(r"catalogued ideas", re.I), "possible directions"),
    (re.compile(r"catalogued", re.I), "known"),
    (re.compile(r"scaffold", re.I), "basic version"),
    (re.compile(r"compile(?:d|r|s)?", re.I), "build"),
)


def field_label(value: str) -> str:
    """Turn an internal field name into a readable label."""
    raw = str(value or "").strip().replace("_", " ")
    if not raw:
        return "details"
    words = raw.split()
    return " ".join(_FIELD_WORDS.get(word.lower(), word) for word in words)


def job_label(job: str | None) -> str:
    """Return the phrase a person sees for an internal job id."""
    return JOB_LABELS.get(str(job or ""), field_label(str(job or "")))


def job_pitch(jobs: list[str] | tuple[str, ...] | None) -> str:
    """Describe a set of app capabilities without exposing taxonomy ids."""
    labels = [_JOB_PITCHES[job] for job in jobs or [] if job in _JOB_PITCHES]
    return " · ".join(dict.fromkeys(labels))


def humanize_message(message: str | None) -> str:
    """Soften known internal wording while preserving user-authored text."""
    out = str(message or "")
    for pattern, replacement in _COPY_REPLACEMENTS:
        out = pattern.sub(replacement, out)

    # The main journey does not need operation names, confidence percentages,
    # or object ids.  Keep the raw message in ``technical_details`` instead.
    out = re.sub(r"\s*\(round \d+\)", "", out, flags=re.I)
    out = re.sub(r"\s*\(confidence \d+%,?\s*[^)]*\)", "", out, flags=re.I)
    out = re.sub(r"\bobject\(s\)\b", "things", out, flags=re.I)
    out = re.sub(r"\bobject\b", "thing", out, flags=re.I)
    out = re.sub(r"\bstatus:\s*(?:ledger_only|unfiled)\b", "not filed yet", out, flags=re.I)
    out = re.sub(r"\bRouted:\s*", "Went to the right place: ", out)
    out = re.sub(r"\bRouted\b", "Went to the right place", out)
    out = re.sub(r"\broute(?:d|s|ing)?\b", "place", out, flags=re.I)
    out = re.sub(r"\bSchema for\b", "What the app keeps track of for", out, flags=re.I)
    out = re.sub(r"\bProposed edit to\b", "Here is the change to", out, flags=re.I)
    out = re.sub(r"\bMigration\b", "App update", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


def based_on(session: Any) -> str:
    """Return a truthful, short source label for the release surface."""
    tier = str(getattr(session, "bridge_tier", "") or "")
    if tier == "reviewed_corpus":
        return "reviewed sources and your choices"
    if tier == "live_search":
        return "current sources and your choices"
    if tier == "model_knowledge":
        return "your notes and general guidance"
    if tier == "fallback_demo":
        return "your notes"
    if getattr(session, "design_mode", "") == "starter":
        return "built-in guidance and your choices"
    if getattr(session, "design_mode", "") in {"atlas", "scaffold"}:
        return "your notes and the choices you made"
    return "your choices"


def _stage_status(current: str, done: bool = False) -> str:
    if done:
        return "done"
    return "active" if current else "pending"


def progress_for(session: Any, turn: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Build a truthful progress rail for web, CLI, and assistive technology."""
    state = str((turn or {}).get("state") or getattr(session, "state", ""))
    acceptance = (turn or {}).get("acceptance") or getattr(session, "acceptance", {}) or {}
    has_second_note = bool((turn or {}).get("held_out")) or len(
        getattr(session, "elicited_samples", []) or []
    ) >= 2
    has_pack = bool((turn or {}).get("pack")) or bool(getattr(session, "pack_path", None))
    real_captures_value = (turn or {}).get("real_captures")
    if real_captures_value is None:
        real_captures_value = getattr(session, "real_captures", 0)
    real_captures = int(str(real_captures_value or 0))
    acceptance_done = bool(acceptance.get("covered")) or has_second_note

    order = [
        ("focus", "Your focus"),
        ("notes", "Your notes"),
        ("ideas", "App ideas"),
        ("build", "Putting your app together"),
        ("check", "Second note"),
        ("try", "First use"),
        ("ready", "Ready"),
    ]
    completed = {
        "focus": state not in {"fork", "failed"},
        "notes": state not in {"fork", "elicit"} and (has_second_note or state not in {"looks"}),
        "ideas": state not in {"fork", "looks"} and bool(getattr(session, "selected_ideas", [])),
        "build": has_pack,
        "check": acceptance_done and state not in {"fork", "looks", "elicit"},
        "try": real_captures >= 1,
        "ready": state == "done" or str((turn or {}).get("status") or "") == "live",
    }
    active_by_state = {
        "fork": "focus",
        "looks": "ideas",
        "elicit": "notes",
        "model_confirm": "build",
        "interview": "build",
        "schema_preview": "build",
        "test_drive": "try" if real_captures == 0 else "ready",
        "repair": "check",
        "hardening_confirm": "try",
        "done": "ready",
        "failed": "build",
    }
    active = active_by_state.get(state, "focus")
    result: list[dict[str, str]] = []
    for stage_id, label in order:
        if completed[stage_id]:
            status = "done"
        elif stage_id == active:
            status = "active"
        else:
            status = "pending"
        result.append({"id": stage_id, "label": label, "status": status})
    return result


def release_turn(turn: dict[str, Any], session: Any) -> dict[str, Any]:
    """Attach release copy and progress without changing legacy fields."""
    raw = str(turn.get("message") or "")
    user_message = humanize_message(raw)
    if not user_message:
        user_message = "Your choices are saved. Continue when you are ready."
    if getattr(session, "release_mode", False):
        state = turn.get("state")
        if state == "fork":
            user_message = (
                f"What would you like to do with {str(getattr(session, 'goal', 'this interest')).strip()}? "
                "Choose a direction below, or describe it in your own words."
            )
        elif state == "looks":
            user_message = "Here are a few starting points. Choose one, tell us what to change, or continue."
        elif state == "schema_preview":
            user_message = "Here is what your app will keep track of. Build it, or change direction."
        elif state == "model_confirm":
            user_message = "Use reviewed sources to find more directions, or continue with the notes you have shared."
        elif state == "hardening_confirm":
            user_message = "Here is a small change to review. Apply it, or keep your app as it is."
        elif state == "repair":
            user_message = "A few notes need a little more help. Tell us how one of them should fit."
        elif state == "done":
            user_message = "Your app is ready to use."
        elif state == "test_drive":
            capture = turn.get("capture") or {}
            routed = capture.get("routed") or []
            first = routed[0] if routed else None
            if turn.get("first_use_blocked"):
                user_message = "Your choices are saved. Add one note that goes to the right place before calling it ready."
            elif first and first.get("disposition") not in {"unfiled", "ledger_only"}:
                object_name = field_label(str(first.get("object_type") or "note"))
                user_message = f"Went to the right place: {object_name}."
                if first.get("disposition") == "review":
                    user_message += " It is waiting for your review."
            elif capture:
                user_message = "Your note is safe, but it did not go to the right place yet."
            elif turn.get("held_out"):
                replay = turn["held_out"]
                if replay.get("filed"):
                    object_name = field_label(str(replay.get("object_type") or "note"))
                    user_message = f"Your app is ready to try. Your second note went to the right place: {object_name}."
                else:
                    user_message = "Your app is ready to try. Your second note is safe, but it did not go to the right place yet."
            elif getattr(session, "elicited_samples", None):
                user_message = "Your app is ready to try. Based on your notes and choices, add a real note to see how it fits."
            else:
                user_message = "Your app is ready to try. Built from your notes so far, it is ready for a real note."
    turn["user_message"] = user_message
    turn["based_on"] = based_on(session)
    turn["progress"] = progress_for(session, turn)
    turn["phase"] = next(
        (item["id"] for item in turn["progress"] if item["status"] == "active"),
        "ready" if turn.get("done") else "focus",
    )
    turn["release_mode"] = bool(getattr(session, "release_mode", False))
    if isinstance(turn.get("neighborhood"), dict) and getattr(session, "release_mode", False):
        neighborhood = deepcopy(turn["neighborhood"])
        if neighborhood.get("unindexed"):
            # A missing atlas entry is not a reason to offer unrelated
            # categories. The note examples are the next useful signal.
            neighborhood["refine"] = []
            neighborhood["expand"] = []
        turn["neighborhood"] = neighborhood
    if raw and raw != user_message:
        turn["technical_details"] = {"message": raw, "state": turn.get("state")}
    if turn.get("elicit"):
        step = turn["elicit"]
        turn["second_note"] = {
            "index": step.get("index", 1),
            "of": step.get("of", 2),
            "is_second": bool(step.get("held_out")),
        }
    return turn
