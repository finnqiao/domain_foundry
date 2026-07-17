"""Correction & supersession workflow (P3)."""

from domain_foundry_core.corrections.intent import has_correction_intent
from domain_foundry_core.corrections.service import CorrectionReceipt, CorrectionService

__all__ = ["CorrectionService", "CorrectionReceipt", "has_correction_intent"]
