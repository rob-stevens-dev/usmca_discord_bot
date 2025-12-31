"""Classification engine for USMCA Bot.

This package provides ML-based content classification including toxicity detection
and sentiment analysis.
"""

from usmca_bot.classification.engine import ClassificationEngine
from usmca_bot.classification.toxicity import ToxicityDetector

__all__ = ["ClassificationEngine", "ToxicityDetector"]
