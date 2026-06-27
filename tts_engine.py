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
    def speech_unit_texts(
        self,
        text: str,
        speaker: str | None = None,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> list[str]:
        """Split one segment into the text units that should become audio files."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        speaker: str,
        output_path: Path,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> None:
        """Synthesize one segment and save it as a WAV file."""


class ChatterboxEngine(BaseTTSEngine):
    """Adapter around the Chatterbox TTS package."""

    EMOTION_OPTIONS = {
        "neutral": {"exaggeration": 0.35},
        "calm": {"exaggeration": 0.25},
        "warm": {"exaggeration": 0.45},
        "happy": {"exaggeration": 0.65},
        # Keep excited controlled for OPIC practice; high exaggeration often
        # makes Chatterbox rush even when the pace tag is slow.
        "excited": {"exaggeration": 0.55},
        "surprised": {"exaggeration": 0.75},
        "worried": {"exaggeration": 0.60},
        "concerned": {"exaggeration": 0.50},
        "disappointed": {"exaggeration": 0.50},
        "embarrassed": {"exaggeration": 0.45},
        "frustrated": {"exaggeration": 0.70},
        "relieved": {"exaggeration": 0.48},
        "grateful": {"exaggeration": 0.55},
        "curious": {"exaggeration": 0.50},
        "polite": {"exaggeration": 0.40},
        "professional": {"exaggeration": 0.30},
        "reassuring": {"exaggeration": 0.42},
        "determined": {"exaggeration": 0.55},
        "cooperative": {"exaggeration": 0.40},
    }
    PACE_OPTIONS = {
        "slow": {"cfg_weight": 0.20, "sentence_pause_ms": 351},
        "medium": {"cfg_weight": 0.24, "sentence_pause_ms": 243},
        "fast": {"cfg_weight": 0.32, "sentence_pause_ms": 135},
    }
    USER_GLOBAL_PACE_MULTIPLIER = 0.93
    USER_PACE_MULTIPLIER = 0.70
    _PAUSE_PATTERN = re.compile(
        r"(?:<pause:([0-9]+(?:\.[0-9]+)?)>|\[pause:([0-9]+(?:\.[0-9]+)?)\])",
        re.IGNORECASE,
    )

    def __init__(
        self,
        sample_rate: int,
        voices: dict[str, str | None],
        device: str = "auto",
        model_options: dict[str, Any] | None = None,
        max_chunk_chars: int = 220,
        sentence_pause_ms: int = 180,
        pace_override: str | None = None,
        emotion_overrides: dict[str, str] | None = None,
        voice_lead_in_ms: int = 45,
        voice_fade_in_ms: int = 35,
        chunk_fade_out_ms: int = 20,
    ) -> None:
        self.sample_rate = sample_rate
        self.voices = {key.upper(): value for key, value in voices.items()}
        self.device = self._resolve_device(device)
        self.model_options = model_options or {}
        self.max_chunk_chars = max_chunk_chars
        self.sentence_pause_ms = sentence_pause_ms
        self.pace_override = pace_override
        self.emotion_overrides = emotion_overrides or {}
        self.voice_lead_in_ms = voice_lead_in_ms
        self.voice_fade_in_ms = voice_fade_in_ms
        self.chunk_fade_out_ms = chunk_fade_out_ms
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

    def synthesize(
        self,
        text: str,
        speaker: str,
        output_path: Path,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> None:
        if not text.strip():
            raise TTSError(f"Cannot synthesize empty text for speaker {speaker}.")

        voice_path = self.voices.get(speaker.upper())
        if voice_path and not Path(voice_path).is_file():
            raise TTSError(f"Voice file for {speaker} does not exist: {voice_path}")

        model = self._load_model()
        generate_options, sentence_pause_ms = self._style_options(
            emotion, pace, speaker
        )
        voice_key = str(Path(voice_path).resolve()) if voice_path else None
        if voice_key in self._conditionals:
            model.conds = self._conditionals[voice_key]
            audio_prompt_path = None
        else:
            audio_prompt_path = voice_path

        try:
            model_rate = int(getattr(model, "sr", self.sample_rate))
            waveforms = []
            pauses_after: list[int] = []
            for chunk, pause_after_ms in self._speech_units(
                text, sentence_pause_ms
            ):
                chunk_options = dict(generate_options)
                if audio_prompt_path:
                    chunk_options["audio_prompt_path"] = audio_prompt_path
                waveform = self._resample_if_needed(
                    model.generate(chunk, **chunk_options), model_rate
                )
                waveform = self._fade_out_chunk(waveform)
                if voice_path:
                    waveform = self._smooth_cloned_voice_start(waveform)
                waveforms.append(waveform)
                pauses_after.append(pause_after_ms)
                if audio_prompt_path:
                    self._conditionals[voice_key] = model.conds
                    audio_prompt_path = None
            waveform = self._join_waveforms(waveforms, pauses_after)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_waveform(waveform, output_path)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Chatterbox failed for speaker {speaker}: {exc}") from exc

    def speech_unit_texts(
        self,
        text: str,
        speaker: str | None = None,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> list[str]:
        if not text.strip():
            raise TTSError("Cannot split empty text into speech units.")
        _, sentence_pause_ms = self._style_options(emotion, pace, speaker)
        return [chunk for chunk, _ in self._speech_units(text, sentence_pause_ms)]

    def _style_options(
        self, emotion: str | None, pace: str | None, speaker: str | None = None
    ) -> tuple[dict[str, Any], int]:
        generate_options = dict(self.model_options)
        effective_emotion = self.emotion_overrides.get(emotion or "", emotion)
        if effective_emotion:
            generate_options.update(self.EMOTION_OPTIONS.get(effective_emotion, {}))

        effective_pace = self.pace_override or pace
        pace_options = self.PACE_OPTIONS.get(effective_pace or "", {})
        generate_options.update(
            {
                key: value
                for key, value in pace_options.items()
                if key != "sentence_pause_ms"
            }
        )
        sentence_pause_ms = int(
            pace_options.get("sentence_pause_ms", self.sentence_pause_ms)
        )
        if speaker and speaker.upper() == "USER":
            pace_multiplier = self.USER_PACE_MULTIPLIER * self.USER_GLOBAL_PACE_MULTIPLIER
            if "cfg_weight" in generate_options:
                generate_options["cfg_weight"] = generate_options["cfg_weight"] * (
                    pace_multiplier
                )
            sentence_pause_ms = round(sentence_pause_ms / pace_multiplier)

        return generate_options, sentence_pause_ms

    def _resample_if_needed(self, waveform: Any, source_rate: int) -> Any:
        if source_rate == self.sample_rate:
            return waveform
        try:
            import torchaudio.functional as audio_functional
        except ImportError as exc:
            raise TTSError("torchaudio is required to resample Chatterbox audio.") from exc
        return audio_functional.resample(waveform, source_rate, self.sample_rate)

    def _smooth_cloned_voice_start(self, waveform: Any) -> Any:
        """Mask short voice-cloning transients without changing pitch or tempo."""
        try:
            import torch
        except ImportError as exc:
            raise TTSError("torch is required to smooth generated audio.") from exc

        audio = waveform.unsqueeze(0) if getattr(waveform, "ndim", 0) == 1 else waveform
        fade_samples = min(
            round(self.sample_rate * self.voice_fade_in_ms / 1000),
            audio.shape[-1],
        )
        if fade_samples:
            fade = torch.linspace(
                0.0,
                1.0,
                fade_samples,
                dtype=audio.dtype,
                device=audio.device,
            )
            audio = audio.clone()
            audio[..., :fade_samples] *= fade

        lead_samples = round(self.sample_rate * self.voice_lead_in_ms / 1000)
        if lead_samples:
            lead_in = torch.zeros(
                (*audio.shape[:-1], lead_samples),
                dtype=audio.dtype,
                device=audio.device,
            )
            audio = torch.cat((lead_in, audio), dim=-1)
        return audio

    def _fade_out_chunk(self, waveform: Any) -> Any:
        """Reduce short synthesis tails immediately before pauses."""
        if not self.chunk_fade_out_ms:
            return waveform
        try:
            import torch
        except ImportError as exc:
            raise TTSError("torch is required to smooth generated audio.") from exc

        audio = waveform.unsqueeze(0) if getattr(waveform, "ndim", 0) == 1 else waveform
        fade_samples = min(
            round(self.sample_rate * self.chunk_fade_out_ms / 1000),
            audio.shape[-1],
        )
        if not fade_samples:
            return audio
        fade = torch.linspace(
            1.0,
            0.0,
            fade_samples,
            dtype=audio.dtype,
            device=audio.device,
        )
        audio = audio.clone()
        audio[..., -fade_samples:] *= fade
        return audio

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

    def _speech_units(
        self, text: str, sentence_pause_ms: int
    ) -> list[tuple[str, int]]:
        units: list[tuple[str, int]] = []
        position = 0
        for pause_match in self._PAUSE_PATTERN.finditer(text):
            pause_seconds = float(pause_match.group(1) or pause_match.group(2))
            spoken_text = text[position : pause_match.start()]
            chunks = self._split_text(spoken_text)
            for index, chunk in enumerate(chunks):
                pause_ms = (
                    round(pause_seconds * 1000)
                    if index == len(chunks) - 1
                    else sentence_pause_ms
                )
                units.append((chunk, pause_ms))
            position = pause_match.end()

        chunks = self._split_text(text[position:])
        units.extend(
            (chunk, sentence_pause_ms if index < len(chunks) - 1 else 0)
            for index, chunk in enumerate(chunks)
        )
        if not units:
            raise TTSError("Segment contains pauses but no text to synthesize.")
        return units

    def _join_waveforms(
        self, waveforms: list[Any], pauses_after: list[int] | None = None
    ) -> Any:
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
        pauses_after = pauses_after or [
            self.sentence_pause_ms for _ in normalized
        ]
        parts: list[Any] = []
        for index, waveform in enumerate(normalized):
            parts.append(waveform)
            if index < len(normalized) - 1:
                silence_length = round(
                    self.sample_rate * pauses_after[index] / 1000
                )
                if silence_length:
                    parts.append(
                        torch.zeros(
                            (normalized[0].shape[0], silence_length),
                            dtype=normalized[0].dtype,
                            device=normalized[0].device,
                        )
                    )
        return torch.cat(parts, dim=-1)

    def _save_waveform(self, waveform: Any, output_path: Path) -> None:
        try:
            import torchaudio
        except ImportError as exc:
            raise TTSError("torchaudio is required to save Chatterbox audio.") from exc

        if getattr(waveform, "ndim", 0) == 1:
            waveform = waveform.unsqueeze(0)
        torchaudio.save(str(output_path), waveform.cpu(), self.sample_rate)
