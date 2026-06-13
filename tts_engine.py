"""Pluggable TTS engines.

All Chatterbox-specific imports and API calls are intentionally kept here.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class TTSError(RuntimeError):
    """Raised when speech synthesis fails."""


class BaseTTSEngine(ABC):
    """Interface implemented by text-to-speech engines."""

    @abstractmethod
    def synthesize(self, text: str, speaker: str, output_path: Path) -> None:
        """Synthesize one segment and save it as a WAV file."""


class ChatterboxEngine(BaseTTSEngine):
    """Adapter around the Chatterbox TTS package."""

    def __init__(
        self,
        sample_rate: int,
        voices: dict[str, str | None],
        device: str = "auto",
        model_options: dict[str, Any] | None = None,
        max_chunk_chars: int = 220,
        sentence_pause_ms: int = 180,
    ) -> None:
        self.sample_rate = sample_rate
        self.voices = {key.upper(): value for key, value in voices.items()}
        self.device = self._resolve_device(device)
        self.model_options = model_options or {}
        self.max_chunk_chars = max_chunk_chars
        self.sentence_pause_ms = sentence_pause_ms
        self._model: Any = None
        self._conditionals: dict[str | None, Any] = {}

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from chatterbox.tts import ChatterboxTTS
        except ImportError as exc:
            raise TTSError(
                "Chatterbox is not installed. Install project dependencies first."
            ) from exc

        try:
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        except Exception as exc:
            raise TTSError(f"Could not load Chatterbox on {self.device}: {exc}") from exc
        self._conditionals[None] = self._model.conds
        return self._model

    def synthesize(self, text: str, speaker: str, output_path: Path) -> None:
        if not text.strip():
            raise TTSError(f"Cannot synthesize empty text for speaker {speaker}.")

        voice_path = self.voices.get(speaker.upper())
        if voice_path and not Path(voice_path).is_file():
            raise TTSError(f"Voice file for {speaker} does not exist: {voice_path}")

        model = self._load_model()
        generate_options = dict(self.model_options)
        voice_key = str(Path(voice_path).resolve()) if voice_path else None
        if voice_key in self._conditionals:
            model.conds = self._conditionals[voice_key]
            audio_prompt_path = None
        else:
            audio_prompt_path = voice_path

        try:
            model_rate = int(getattr(model, "sr", self.sample_rate))
            waveforms = []
            for chunk in self._split_text(text):
                chunk_options = dict(generate_options)
                if audio_prompt_path:
                    chunk_options["audio_prompt_path"] = audio_prompt_path
                waveform = self._resample_if_needed(
                    model.generate(chunk, **chunk_options), model_rate
                )
                waveforms.append(waveform)
                if audio_prompt_path:
                    self._conditionals[voice_key] = model.conds
                    audio_prompt_path = None
            waveform = self._join_waveforms(waveforms)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_waveform(waveform, output_path)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Chatterbox failed for speaker {speaker}: {exc}") from exc

    def _resample_if_needed(self, waveform: Any, source_rate: int) -> Any:
        if source_rate == self.sample_rate:
            return waveform
        try:
            import torchaudio.functional as audio_functional
        except ImportError as exc:
            raise TTSError("torchaudio is required to resample Chatterbox audio.") from exc
        return audio_functional.resample(waveform, source_rate, self.sample_rate)

    def _split_text(self, text: str) -> list[str]:
        """Split long prompts at sentence boundaries for more stable generation."""
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", text.strip())
            if part.strip()
        ]
        chunks: list[str] = []
        for sentence in sentences:
            words = sentence.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > self.max_chunk_chars:
                    chunks.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                chunks.append(current)
        return chunks

    def _join_waveforms(self, waveforms: list[Any]) -> Any:
        if len(waveforms) == 1:
            return waveforms[0]
        try:
            import torch
        except ImportError as exc:
            raise TTSError("torch is required to assemble generated audio.") from exc

        normalized = [
            waveform.unsqueeze(0) if getattr(waveform, "ndim", 0) == 1 else waveform
            for waveform in waveforms
        ]
        silence_length = round(self.sample_rate * self.sentence_pause_ms / 1000)
        silence = torch.zeros(
            (normalized[0].shape[0], silence_length),
            dtype=normalized[0].dtype,
            device=normalized[0].device,
        )
        parts: list[Any] = []
        for index, waveform in enumerate(normalized):
            if index and silence_length:
                parts.append(silence)
            parts.append(waveform)
        return torch.cat(parts, dim=-1)

    def _save_waveform(self, waveform: Any, output_path: Path) -> None:
        try:
            import torchaudio
        except ImportError as exc:
            raise TTSError("torchaudio is required to save Chatterbox audio.") from exc

        if getattr(waveform, "ndim", 0) == 1:
            waveform = waveform.unsqueeze(0)
        torchaudio.save(str(output_path), waveform.cpu(), self.sample_rate)
