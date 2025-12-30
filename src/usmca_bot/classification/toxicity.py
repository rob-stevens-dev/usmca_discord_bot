"""Toxicity detection using Detoxify ML model.

This module wraps the Detoxify library for toxicity classification,
providing a clean interface for Discord message analysis.
"""

import asyncio
from functools import lru_cache
from typing import Literal

import torch
from detoxify import Detoxify

from usmca_bot.config import Settings
from usmca_bot.database.models import ToxicityScores


class ToxicityDetector:
    """Toxicity detection using Detoxify transformer model.

    This class loads and manages the Detoxify model for analyzing text toxicity.
    The model provides scores for multiple toxicity categories.

    Attributes:
        settings: Application settings.
        model: Loaded Detoxify model instance.
        device: Torch device ('cpu' or 'cuda').
    """

    def __init__(
        self,
        settings: Settings,
        model_type: Literal["original", "unbiased", "multilingual"] = "unbiased",
    ) -> None:
        """Initialize toxicity detector.

        Args:
            settings: Application settings.
            model_type: Detoxify model variant to use.
                - 'original': Original model (English)
                - 'unbiased': Unbiased model (English, recommended)
                - 'multilingual': Multilingual support (slower)

        Note:
            Model is loaded lazily on first prediction to avoid
            unnecessary resource consumption during testing.
        """
        self.settings = settings
        self.model_type = model_type
        self.model: Detoxify | None = None
        self.device = settings.model_device

    def _load_model(self) -> Detoxify:
        """Load Detoxify model.

        Returns:
            Loaded Detoxify model instance.

        Raises:
            RuntimeError: If model loading fails.
        """
        if self.model is None:
            try:
                self.model = Detoxify(
                    model_type=self.model_type,
                    device=self.device,
                    cache_dir=self.settings.model_cache_dir,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load Detoxify model: {e}") from e
        
        return self.model

    async def predict(self, text: str) -> ToxicityScores:
        """Predict toxicity scores for text.

        Args:
            text: Text content to analyze.

        Returns:
            ToxicityScores object with all category scores.

        Raises:
            RuntimeError: If prediction fails.

        Example:
```python
            detector = ToxicityDetector(settings)
            scores = await detector.predict("your message here")
            print(f"Toxicity: {scores.toxicity:.2f}")
```
        """
        if not text or not text.strip():
            # Empty text gets zero scores
            return ToxicityScores(
                toxicity=0.0,
                severe_toxicity=0.0,
                obscene=0.0,
                threat=0.0,
                insult=0.0,
                identity_attack=0.0,
            )

        try:
            # Run model inference in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, self._predict_sync, text
            )
            
            return ToxicityScores(
                toxicity=float(results["toxicity"]),
                severe_toxicity=float(results["severe_toxicity"]),
                obscene=float(results["obscene"]),
                threat=float(results["threat"]),
                insult=float(results["insult"]),
                identity_attack=float(results["identity_attack"]),
            )
        except Exception as e:
            raise RuntimeError(f"Toxicity prediction failed: {e}") from e

    def _predict_sync(self, text: str) -> dict[str, float]:
        """Synchronous prediction (runs in thread pool).

        Args:
            text: Text to analyze.

        Returns:
            Dictionary of toxicity scores.
        """
        model = self._load_model()
        
        # Detoxify.predict returns dict with numpy arrays
        results = model.predict(text)
        
        # Convert numpy values to Python floats
        return {
            key: float(value.item() if hasattr(value, "item") else value)
            for key, value in results.items()
        }

    async def predict_batch(
        self, texts: list[str], batch_size: int = 32
    ) -> list[ToxicityScores]:
        """Predict toxicity scores for multiple texts.

        More efficient than calling predict() multiple times due to batching.

        Args:
            texts: List of text strings to analyze.
            batch_size: Number of texts to process in each batch.

        Returns:
            List of ToxicityScores objects, same order as input.

        Raises:
            RuntimeError: If prediction fails.

        Example:
```python
            detector = ToxicityDetector(settings)
            texts = ["message 1", "message 2", "message 3"]
            scores_list = await detector.predict_batch(texts)
```
        """
        if not texts:
            return []

        # Filter empty texts and track indices
        non_empty_texts = []
        non_empty_indices = []
        
        for i, text in enumerate(texts):
            if text and text.strip():
                non_empty_texts.append(text)
                non_empty_indices.append(i)

        # Initialize results with zero scores
        results = [
            ToxicityScores(
                toxicity=0.0,
                severe_toxicity=0.0,
                obscene=0.0,
                threat=0.0,
                insult=0.0,
                identity_attack=0.0,
            )
            for _ in texts
        ]

        if not non_empty_texts:
            return results

        try:
            # Run batch prediction in thread pool
            loop = asyncio.get_event_loop()
            batch_results = await loop.run_in_executor(
                None, self._predict_batch_sync, non_empty_texts, batch_size
            )
            
            # Map results back to original indices
            for idx, batch_result in zip(non_empty_indices, batch_results):
                results[idx] = ToxicityScores(
                    toxicity=float(batch_result["toxicity"]),
                    severe_toxicity=float(batch_result["severe_toxicity"]),
                    obscene=float(batch_result["obscene"]),
                    threat=float(batch_result["threat"]),
                    insult=float(batch_result["insult"]),
                    identity_attack=float(batch_result["identity_attack"]),
                )
            
            return results
        except Exception as e:
            raise RuntimeError(f"Batch toxicity prediction failed: {e}") from e

    def _predict_batch_sync(
        self, texts: list[str], batch_size: int
    ) -> list[dict[str, float]]:
        """Synchronous batch prediction (runs in thread pool).

        Args:
            texts: List of texts to analyze.
            batch_size: Batch size for processing.

        Returns:
            List of dictionaries containing toxicity scores.
        """
        model = self._load_model()
        
        # Process in batches to manage memory
        all_results = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_results = model.predict(batch)
            
            # Convert batch results to list of dicts
            num_samples = len(batch)
            for j in range(num_samples):
                sample_result = {
                    key: float(
                        value[j].item() if hasattr(value[j], "item") else value[j]
                    )
                    for key, value in batch_results.items()
                }
                all_results.append(sample_result)
        
        return all_results

    def unload_model(self) -> None:
        """Unload model from memory.

        Useful for freeing GPU/CPU memory when detector is not needed.
        Model will be reloaded on next prediction.
        """
        if self.model is not None:
            del self.model
            self.model = None
            
            # Clear CUDA cache if using GPU
            if self.device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()

    @property
    def is_loaded(self) -> bool:
        """Check if model is currently loaded in memory.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self.model is not None

    def get_model_info(self) -> dict[str, str]:
        """Get information about the loaded model.

        Returns:
            Dictionary containing model metadata.
        """
        return {
            "model_type": self.model_type,
            "device": self.device,
            "cache_dir": self.settings.model_cache_dir,
            "is_loaded": str(self.is_loaded),
        }


@lru_cache(maxsize=1)
def get_toxicity_detector(settings: Settings) -> ToxicityDetector:
    """Get cached toxicity detector instance.

    Args:
        settings: Application settings.

    Returns:
        Cached ToxicityDetector instance.

    Note:
        This function caches the detector to avoid creating multiple instances.
        The cache is cleared when settings change.
    """
    return ToxicityDetector(settings)