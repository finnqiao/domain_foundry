"""Seeds shape the app, so the summary has to reach the brief.

The pipeline already takes artifacts on a brief: short lines describing what the
person already keeps. A seed produces exactly that, from real counts instead of
a guess, plus the ``SeedProvenance`` entries the research stage marks its
sources against.

What travels is shapes and counts: how many rows, which columns, which values
repeat, what span of dates. Never the rows. A place name or a species name from
a personal upload is personal, even though it looks like a harmless list, so
those stay behind and only the count of them goes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.foundry.models import SeedProvenance
from domain_foundry_core.seed.models import SeedRead, SeedSummary, summarize

# The one ask, worded once, used everywhere the flow offers seeding.
SEED_ASK = (
    "If you have records already, I can start the app full instead of empty. "
    "Point me at a spreadsheet, a notes folder, photos, an export from another "
    "app or your email, and one or two pages you trust, like a field guide or a "
    "species checklist. Or say just build and I will start from nothing."
)

# What counts as "carry on without seeding".
SEED_DECLINE_WORDS: tuple[str, ...] = (
    "just build",
    "skip",
    "no thanks",
    "none",
    "nothing",
    "build it",
)

# The pipeline caps a brief at twenty artifacts, each under two thousand
# characters. Seeds stay well inside that so a brief still has room for the
# user's own words.
MAX_ARTIFACT_LINES_PER_SEED = 4
MAX_ARTIFACT_CHARS = 1_800


@dataclass
class SeedBriefInputs:
    """What a seed contributes to a brief, ready to pass straight through."""

    artifacts: list[str] = field(default_factory=list)
    seeds: list[SeedProvenance] = field(default_factory=list)
    summaries: list[SeedSummary] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifacts": list(self.artifacts),
            "seeds": [item.model_dump(mode="json") for item in self.seeds],
            "summaries": [item.as_dict() for item in self.summaries],
        }


def declined_seeding(reply: str) -> bool:
    """True when the person said carry on without it."""

    text = (reply or "").strip().casefold()
    return any(word in text for word in SEED_DECLINE_WORDS)


def seed_artifact_lines(summary: SeedSummary) -> list[str]:
    """Describe one seed in the short lines a brief takes.

    Counts and column names, not contents. A repeated list is reported as a
    number and the column it lives in, because the values themselves are the
    person's own vocabulary.
    """

    lines: list[str] = []
    if summary.kind == "public_link":
        head = f"A page I trust: {summary.label}."
        if summary.documents:
            head += " Sections: " + ", ".join(summary.documents[:6]) + "."
        lines.append(head[:MAX_ARTIFACT_CHARS])
        return lines

    head = f"My own records: {summary.label}, {summary.row_count} rows"
    if summary.columns:
        head += " with " + ", ".join(summary.columns[:8])
    lines.append((head + ".")[:MAX_ARTIFACT_CHARS])

    if summary.date_range:
        first, last = summary.date_range
        lines.append(f"The records run from {first} to {last}.")

    for item in summary.repeated[: MAX_ARTIFACT_LINES_PER_SEED - len(lines)]:
        lines.append(
            f"The same {item.distinct} values keep coming back in {item.column}, "
            "so that column is a list of its own."
        )

    return [line[:MAX_ARTIFACT_CHARS] for line in lines[:MAX_ARTIFACT_LINES_PER_SEED]]


def seed_brief_inputs(reads: list[SeedRead]) -> SeedBriefInputs:
    """Everything the seeds give a brief, in one bundle.

    Pass ``inputs.artifacts`` to the pipeline's ``artifacts`` argument and
    ``inputs.seeds`` onto the research brief. The research stage can then mark
    which evidence came from the user's own records, which came from a page they
    pointed at, and which came from the model.
    """

    artifacts: list[str] = []
    seeds: list[SeedProvenance] = []
    summaries: list[SeedSummary] = []
    for read in reads:
        summary = summarize(read)
        summaries.append(summary)
        seeds.append(read.provenance)
        artifacts.extend(seed_artifact_lines(summary))
    return SeedBriefInputs(artifacts=artifacts, seeds=seeds, summaries=summaries)
