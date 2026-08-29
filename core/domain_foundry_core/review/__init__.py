"""The look review loop: a page you mark up, and the binding it becomes.

`page` builds the static HTML review page. `marks` is the contract for the
`review-marks.json` file the page hands you, and turns it into a `LookBinding`.
`binding` writes that binding back into a spec on disk. `vibe` reads colours
off a reference file you already have.

Nothing here talks to a network.
"""

from .binding import BindingError, bind_look, load_spec_document, write_spec_document
from .marks import (
    MARKS_FILENAME,
    MARKS_VERSION,
    ConceptMarks,
    MarkPin,
    MarksError,
    ReviewMarks,
    check_token_overrides,
    marks_from_choice,
    parse_marks,
    read_marks,
)
from .page import (
    TOKEN_LABELS,
    TOPOLOGY_LABELS,
    ConceptCard,
    ReviewProposal,
    proposal_from_spec,
    render_review_page,
)
from .vibe import VibeError, VibeReading, read_reference

__all__ = [
    "MARKS_FILENAME",
    "MARKS_VERSION",
    "TOKEN_LABELS",
    "TOPOLOGY_LABELS",
    "BindingError",
    "ConceptCard",
    "ConceptMarks",
    "MarkPin",
    "MarksError",
    "ReviewMarks",
    "ReviewProposal",
    "VibeError",
    "VibeReading",
    "bind_look",
    "check_token_overrides",
    "load_spec_document",
    "marks_from_choice",
    "parse_marks",
    "proposal_from_spec",
    "read_marks",
    "read_reference",
    "render_review_page",
    "write_spec_document",
]
