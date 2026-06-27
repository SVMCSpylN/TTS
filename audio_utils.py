"""Audio assembly and export helpers."""

from __future__ import annotations

import wave
from pathlib import Path
from shutil import which
from typing import Sequence


class AudioProcessingError(RuntimeError):
    """Raised when generated audio cannot be assembled or exported."""


def concatenate_wavs(
    wav_paths: Sequence[str | Path],
    output_path: str | Path,
    pause_ms: int | Sequence[int],
    output_format: str = "mp3",
    mp3_bitrate: str = "192k",
    normalize_audio: bool = True,
    output_sample_rate: int = 44100,
    output_channels: int = 2,
) -> Path:
    """Concatenate WAV files with silence between segments and export the result."""
    if not wav_paths:
        raise AudioProcessingError("No WAV segments were provided for concatenation.")
    if isinstance(pause_ms, int):
        if pause_ms < 0:
            raise AudioProcessingError("pause_ms cannot be negative.")
        pauses = [pause_ms] * (len(wav_paths) - 1)
    else:
        pauses = list(pause_ms)
        if len(pauses) != len(wav_paths) - 1:
            raise AudioProcessingError(
                "The number of pause values must be one less than the WAV count."
            )
        if any(value < 0 for value in pauses):
            raise AudioProcessingError("pause_ms cannot be negative.")
    if output_format.lower() != "mp3":
        raise AudioProcessingError(
            f"Unsupported output format '{output_format}'. This project exports MP3."
        )
    if output_sample_rate <= 0:
        raise AudioProcessingError("output_sample_rate must be greater than zero.")
    if output_channels not in (1, 2):
        raise AudioProcessingError("output_channels must be 1 or 2.")

    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise AudioProcessingError(
            "pydub is not installed. Install project dependencies first."
        ) from exc

    _configure_ffmpeg(AudioSegment)

    combined = AudioSegment.empty()
    try:
        for index, wav_path in enumerate(wav_paths):
            path = Path(wav_path)
            if not path.is_file():
                raise AudioProcessingError(f"Generated WAV file is missing: {path}")
            if index:
                combined += AudioSegment.silent(duration=pauses[index - 1])
            combined += _load_wav(AudioSegment, path)

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if normalize_audio:
            from pydub.effects import normalize

            combined = normalize(combined, headroom=1.0)
        combined = combined.set_frame_rate(output_sample_rate)
        combined = combined.set_channels(output_channels)
        combined.export(destination, format="mp3", bitrate=mp3_bitrate)
        return destination
    except AudioProcessingError:
        raise
    except Exception as exc:
        raise AudioProcessingError(
            f"Could not export MP3. Verify that FFmpeg is installed: {exc}"
        ) from exc


def export_wav_to_mp3(
    wav_path: str | Path,
    output_path: str | Path,
    mp3_bitrate: str = "192k",
    normalize_audio: bool = True,
    output_sample_rate: int = 44100,
    output_channels: int = 2,
    tail_silence_ms: int = 0,
) -> Path:
    """Export one generated WAV file to MP3, optionally appending clean silence."""
    if output_sample_rate <= 0:
        raise AudioProcessingError("output_sample_rate must be greater than zero.")
    if output_channels not in (1, 2):
        raise AudioProcessingError("output_channels must be 1 or 2.")
    if tail_silence_ms < 0:
        raise AudioProcessingError("tail_silence_ms cannot be negative.")

    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise AudioProcessingError(
            "pydub is not installed. Install project dependencies first."
        ) from exc

    _configure_ffmpeg(AudioSegment)

    source = Path(wav_path)
    if not source.is_file():
        raise AudioProcessingError(f"Generated WAV file is missing: {source}")

    try:
        audio = _load_wav(AudioSegment, source)
        if normalize_audio:
            from pydub.effects import normalize

            audio = normalize(audio, headroom=1.0)
        if tail_silence_ms:
            audio += AudioSegment.silent(duration=tail_silence_ms)
        audio = audio.set_frame_rate(output_sample_rate)
        audio = audio.set_channels(output_channels)

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        audio.export(destination, format="mp3", bitrate=mp3_bitrate)
        return destination
    except AudioProcessingError:
        raise
    except Exception as exc:
        raise AudioProcessingError(
            f"Could not export MP3. Verify that FFmpeg is installed: {exc}"
        ) from exc


def _configure_ffmpeg(audio_segment: object) -> None:
    if which("ffmpeg"):
        return

    try:
        import imageio_ffmpeg
    except ImportError:
        return

    converter = imageio_ffmpeg.get_ffmpeg_exe()
    audio_segment.converter = converter
    audio_segment.ffmpeg = converter
    audio_segment.ffprobe = converter


def _load_wav(audio_segment: object, path: Path):
    try:
        return _load_wav_with_soundfile(audio_segment, path)
    except ImportError:
        pass
    except Exception as exc:
        raise AudioProcessingError(f"Could not read WAV file {path}: {exc}") from exc

    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error as exc:
        raise AudioProcessingError(f"Could not read WAV file {path}: {exc}") from exc

    return audio_segment(
        data=frames,
        sample_width=sample_width,
        frame_rate=frame_rate,
        channels=channels,
    )


def _load_wav_with_soundfile(audio_segment: object, path: Path):
    import numpy as np
    import soundfile as sf

    data, frame_rate = sf.read(str(path), always_2d=True, dtype="float32")
    if data.size == 0:
        raise AudioProcessingError(f"WAV file is empty: {path}")

    pcm = np.clip(data, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2", copy=False)
    return audio_segment(
        data=pcm.tobytes(),
        sample_width=2,
        frame_rate=frame_rate,
        channels=pcm.shape[1],
    )
