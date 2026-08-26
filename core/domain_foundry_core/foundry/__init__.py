"""Evidence-backed product foundry specification and compilation interfaces."""

from .compiler import BuildArtifact, FoundryCompiler
from .loader import dump_foundry_spec, load_foundry_spec, load_golden_specs
from .models import FoundrySpec
from .pipeline import AcceptanceTask, FoundryPipeline, FoundryProposal

__all__ = [
    "BuildArtifact",
    "AcceptanceTask",
    "FoundryCompiler",
    "FoundryPipeline",
    "FoundryProposal",
    "FoundrySpec",
    "dump_foundry_spec",
    "load_foundry_spec",
    "load_golden_specs",
]
