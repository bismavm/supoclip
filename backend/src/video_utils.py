"""
Utility functions for video-related operations.
Optimized for MoviePy v2, AssemblyAI integration, and high-quality output.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import os
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import tempfile
from types import SimpleNamespace
import requests
import time

import cv2
from moviepy import VideoFileClip, CompositeVideoClip, TextClip, ColorClip
from moviepy.video.fx import CrossFadeIn, CrossFadeOut, FadeIn, FadeOut

import assemblyai as aai
import srt
from datetime import timedelta

from .config import Config
from .caption_templates import get_template, CAPTION_TEMPLATES
from .font_registry import find_font_path
from .smart_cropping import (
    analyze_clip_and_decide_strategy,
    analyze_clip_with_scene_detection,
    CropStrategy,
    apply_letterbox_blur,
    create_stacking_layout,
    create_blur_background,
)
from .ffmpeg_smart_crop import (
    generate_crop_filter,
    process_scene_with_ffmpeg,
    concat_scenes_with_ffmpeg,
    extract_audio_ffmpeg,
)

logger = logging.getLogger(__name__)
config = Config()
TRANSCRIPT_CACHE_SCHEMA_VERSION = 2


def get_font_for_language(language_code: str, requested_font: str = "THEBOLDFONT") -> str:
    """
    Get appropriate font based on language to ensure character support.
    Falls back to language-compatible fonts if default doesn't support the script.
    """
    # Map language codes to compatible fonts
    language_font_map = {
        "th": "NotoSansThai",      # Thai script
        "ja": "NotoSansJP",         # Japanese (kanji, hiragana, katakana)
        "ko": "NotoSansKR",         # Korean (hangul)
        "zh": "NotoSansSC",         # Chinese Simplified
        "ar": "NotoSansArabic",     # Arabic script
        "hi": "NotoSansDevanagari", # Hindi (Devanagari)
    }

    # Check if language needs special font
    fallback_font = language_font_map.get(language_code)

    # Try requested font first, fallback to language-specific if needed
    if fallback_font and config.transcription_language == language_code:
        logger.info(f"Using language-specific font: {fallback_font} for language: {language_code}")
        return fallback_font

    return requested_font


class VideoProcessor:
    """Handles video processing operations with optimized settings."""

    def __init__(
        self,
        font_family: str = "THEBOLDFONT",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
    ):
        # Auto-select font based on transcription language
        language_aware_font = get_font_for_language(config.transcription_language, font_family)

        self.font_family = language_aware_font
        self.font_size = font_size
        self.font_color = font_color
        resolved_font = find_font_path(language_aware_font, allow_all_user_fonts=True)
        if not resolved_font:
            resolved_font = find_font_path("TikTokSans-Regular")
        if not resolved_font:
            resolved_font = find_font_path("THEBOLDFONT")
        self.font_path = str(resolved_font) if resolved_font else ""

    def get_optimal_encoding_settings(
        self, target_quality: str = "high"
    ) -> Dict[str, Any]:
        """Get optimal encoding settings for different quality levels."""
        settings = {
            "high": {
                "codec": "libx264",
                "audio_codec": "aac",
                "audio_bitrate": "256k",
                "preset": "slow",
                "ffmpeg_params": [
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-profile:v",
                    "high",
                    "-movflags",
                    "+faststart",
                    "-sws_flags",
                    "lanczos",
                ],
            },
            "medium": {
                "codec": "libx264",
                "audio_codec": "aac",
                "bitrate": "4000k",
                "audio_bitrate": "192k",
                "preset": "fast",
                "ffmpeg_params": ["-crf", "23", "-pix_fmt", "yuv420p"],
            },
        }
        return settings.get(target_quality, settings["high"])


def _parse_hhmmss_or_mmss_to_ms(value: str) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return int((hours * 3600 + minutes * 60 + seconds) * 1000)
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return int((minutes * 60 + seconds) * 1000)
        seconds = float(parts[0])
        return int(seconds * 1000)
    except ValueError:
        return None


def _format_ms_as_hhmmss(ms: int) -> str:
    total_seconds = max(0, ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _extract_audio_for_gemini(video_path: Path) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        temp_audio_path = Path(tmp_file.name)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(temp_audio_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")
    return temp_audio_path


def _get_media_duration_ms(video_path: Path) -> Optional[int]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        duration_seconds = float((result.stdout or "").strip())
    except Exception:
        return None
    if duration_seconds <= 0:
        return None
    return int(duration_seconds * 1000)


def _extract_text_from_gemini_response(response: Any) -> str:
    text_parts: List[str] = []
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        text_parts.append(direct_text.strip())

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                text_parts.append(part_text.strip())

    if not text_parts:
        return ""
    return "\n".join(text_parts)


def _build_synthetic_utterances_from_plain_text(
    plain_text: str, total_duration_ms: Optional[int]
) -> List[Dict[str, Any]]:
    cleaned = re.sub(r"\s+", " ", plain_text or "").strip()
    cleaned = re.sub(
        r"\[?\d{1,2}:\d{2}(?::\d{2})?\s*-\s*\d{1,2}:\d{2}(?::\d{2})?\]?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    tokens = cleaned.split()
    if not tokens:
        return []

    chunk_size = 14
    chunks = [
        " ".join(tokens[i : i + chunk_size]).strip()
        for i in range(0, len(tokens), chunk_size)
        if " ".join(tokens[i : i + chunk_size]).strip()
    ]
    if not chunks:
        return []

    if total_duration_ms is None or total_duration_ms <= 0:
        # Rough fallback estimate ~450ms per token.
        total_duration_ms = max(15000, len(tokens) * 450)

    slot_ms = max(1000, total_duration_ms // len(chunks))
    utterances: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        start_ms = idx * slot_ms
        end_ms = total_duration_ms if idx == len(chunks) - 1 else (idx + 1) * slot_ms
        utterances.append(
            {
                "start_ms": start_ms,
                "end_ms": max(start_ms + 1000, end_ms),
                "speaker": None,
                "text": chunk,
            }
        )
    return utterances


def _extract_json_object_from_text(raw_text: str) -> Optional[Dict[str, Any]]:
    text = (raw_text or "").strip()
    if not text:
        return None

    fenced_blocks = re.findall(
        r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE
    )
    for block in fenced_blocks:
        candidate = block.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : idx + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return None
    return None


def _build_gemini_transcript_from_response(
    response_text: str, total_duration_ms: Optional[int] = None
):
    data = {}
    try:
        data = json.loads(response_text)
    except Exception:
        extracted = _extract_json_object_from_text(response_text)
        if extracted is not None:
            data = extracted
        else:
            logger.warning(
                "Gemini transcript response was not valid JSON; attempting fallback parser"
            )

    utterances_input = data.get("utterances") if isinstance(data, dict) else None
    if not isinstance(utterances_input, list):
        utterances_input = []

    if not utterances_input and isinstance(data, dict):
        # Alternate schema support.
        segments = data.get("segments")
        if isinstance(segments, list):
            utterances_input = segments

    if not utterances_input:
        # Fallback parser for plain-text timestamp lines.
        time_token = r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
        for line in response_text.splitlines():
            match = re.match(
                rf"^\s*\[?({time_token})\s*-\s*({time_token})\]?\s*(.*)$",
                line.strip(),
            )
            if not match:
                continue
            line_text = re.sub(
                r"^Speaker\s+[A-Za-z0-9_-]+\s*:\s*",
                "",
                match.group(3).strip(),
            ).strip()
            utterances_input.append(
                {
                    "start_time": match.group(1),
                    "end_time": match.group(2),
                    "speaker": None,
                    "text": line_text,
                }
            )

    words: List[SimpleNamespace] = []
    utterances: List[SimpleNamespace] = []
    transcript_text_parts: List[str] = []

    for item in utterances_input:
        if not isinstance(item, dict):
            continue
        start_ms = _parse_hhmmss_or_mmss_to_ms(str(item.get("start_time", "")))
        end_ms = _parse_hhmmss_or_mmss_to_ms(str(item.get("end_time", "")))
        if start_ms is None:
            raw_start = item.get("start")
            if isinstance(raw_start, (int, float)):
                start_ms = int(raw_start)
            elif isinstance(raw_start, str):
                start_ms = _parse_hhmmss_or_mmss_to_ms(raw_start)
        if end_ms is None:
            raw_end = item.get("end")
            if isinstance(raw_end, (int, float)):
                end_ms = int(raw_end)
            elif isinstance(raw_end, str):
                end_ms = _parse_hhmmss_or_mmss_to_ms(raw_end)

        raw_text = (
            item.get("text")
            or item.get("transcript")
            or item.get("utterance")
            or item.get("content")
            or ""
        )
        text = str(raw_text).strip()
        text = re.sub(
            r"^\[?\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*-\s*\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\]?\s*",
            "",
            text,
        ).strip()
        text = re.sub(r"^Speaker\s+[A-Za-z0-9_-]+\s*:\s*", "", text).strip()
        speaker = item.get("speaker") or item.get("speaker_label")
        if isinstance(speaker, str):
            normalized_speaker = speaker.strip()
            if normalized_speaker.lower().startswith("speaker "):
                normalized_speaker = normalized_speaker.split(" ", 1)[1].strip()
            speaker = normalized_speaker or None

        if start_ms is None or end_ms is None or end_ms <= start_ms or not text:
            continue

        transcript_text_parts.append(text)
        utterance_words: List[SimpleNamespace] = []
        tokenized_words = text.split()
        if tokenized_words:
            duration_ms = max(1, end_ms - start_ms)
            slot = max(1, duration_ms // len(tokenized_words))
            for idx, token in enumerate(tokenized_words):
                w_start = start_ms + idx * slot
                w_end = start_ms + (idx + 1) * slot if idx < len(tokenized_words) - 1 else end_ms
                word_obj = SimpleNamespace(
                    text=token,
                    start=w_start,
                    end=max(w_start + 1, w_end),
                    confidence=1.0,
                    speaker=speaker,
                )
                utterance_words.append(word_obj)
                words.append(word_obj)

        utterances.append(
            SimpleNamespace(
                text=text,
                start=start_ms,
                end=end_ms,
                speaker=speaker,
                words=utterance_words,
            )
        )

    if not utterances:
        synthetic = _build_synthetic_utterances_from_plain_text(
            response_text, total_duration_ms
        )
        for item in synthetic:
            start_ms = int(item["start_ms"])
            end_ms = int(item["end_ms"])
            text = str(item["text"]).strip()
            speaker = item.get("speaker")
            transcript_text_parts.append(text)
            tokenized_words = text.split()
            utterance_words: List[SimpleNamespace] = []
            if tokenized_words:
                duration_ms = max(1, end_ms - start_ms)
                slot = max(1, duration_ms // len(tokenized_words))
                for idx, token in enumerate(tokenized_words):
                    w_start = start_ms + idx * slot
                    w_end = (
                        start_ms + (idx + 1) * slot
                        if idx < len(tokenized_words) - 1
                        else end_ms
                    )
                    word_obj = SimpleNamespace(
                        text=token,
                        start=w_start,
                        end=max(w_start + 1, w_end),
                        confidence=0.5,
                        speaker=speaker,
                    )
                    utterance_words.append(word_obj)
                    words.append(word_obj)
            utterances.append(
                SimpleNamespace(
                    text=text,
                    start=start_ms,
                    end=end_ms,
                    speaker=speaker,
                    words=utterance_words,
                )
            )

    if not utterances:
        raise RuntimeError(
            "No timestamped utterances were extracted from Gemini response"
        )

    return SimpleNamespace(
        text="\n".join(transcript_text_parts),
        words=words,
        utterances=utterances,
    )


def _get_video_transcript_google_genai(video_path: Path) -> str:
    logger.info("Starting Google Gen AI transcription via Vertex AI")
    if not config.has_google_vertex_credentials():
        raise RuntimeError(
            "Vertex AI auth is not configured. Set GOOGLE_GENAI_USE_VERTEXAI=true and GOOGLE_CLOUD_PROJECT."
        )

    from google import genai
    from google.genai import types

    audio_path = _extract_audio_for_gemini(video_path)
    try:
        total_duration_ms = _get_media_duration_ms(video_path)
        audio_bytes = audio_path.read_bytes()
        client = genai.Client(
            vertexai=True,
            project=config.google_cloud_project,
            location=config.google_cloud_location,
            http_options=types.HttpOptions(api_version="v1"),
        )

        # Build language-specific prompt with full language names
        language_map = {
            "ms": "Malay (Bahasa Malaysia/Melayu)",
            "id": "Indonesian (Bahasa Indonesia)",
            "en": "English",
            "th": "Thai",
            "ja": "Japanese",
            "ko": "Korean",
            "zh": "Chinese",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "pt": "Portuguese",
            "ru": "Russian",
            "ar": "Arabic",
            "hi": "Hindi",
            "it": "Italian",
            "nl": "Dutch",
            "pl": "Polish",
            "tr": "Turkish",
            "vi": "Vietnamese",
        }

        # Build strong language instruction
        if config.transcription_language != "auto":
            language_name = language_map.get(config.transcription_language, config.transcription_language)
            prompt = (
                f"You are transcribing audio in {language_name}. "
                f"CRITICAL RULES:\n"
                f"1. The audio is spoken in {language_name}\n"
                f"2. Transcribe EXACTLY what you hear in {language_name}\n"
                f"3. DO NOT translate to any other language\n"
                f"4. Keep all text in original {language_name}\n\n"
                f"Return only JSON in this schema: "
                "{'utterances':[{'start_time':'HH:MM:SS','end_time':'HH:MM:SS','speaker':'Speaker A','text':'...'}]}. "
                "Use accurate timestamps from the audio and include all speech."
            )
        else:
            prompt = (
                "Transcribe this audio into JSON. Return only JSON in this schema: "
                "{'utterances':[{'start_time':'HH:MM:SS','end_time':'HH:MM:SS','speaker':'Speaker A','text':'...'}]}. "
                "Use accurate timestamps from the audio and include all speech."
            )
        logger.info(f"Gemini transcription language: {config.transcription_language}")
        response = client.models.generate_content(
            model=config.gemini_transcription_model,
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type="audio/wav",
                ),
            ],
            config=types.GenerateContentConfig(
                audio_timestamp=True,
                response_mime_type="application/json",
            ),
        )
        response_text = _extract_text_from_gemini_response(response)
        transcript = _build_gemini_transcript_from_response(
            response_text,
            total_duration_ms=total_duration_ms,
        )
        formatted_lines = format_transcript_for_analysis(transcript)
        cache_transcript_data(video_path, transcript)
        result = "\n".join(formatted_lines)
        logger.info(
            "Google Gen AI transcript formatted: %s segments, %s chars",
            len(formatted_lines),
            len(result),
        )
        return result
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove temporary audio file: %s", audio_path)


def _get_video_transcript_assemblyai(video_path: Path, speech_model: str = "best") -> str:
    """Get transcript using AssemblyAI with word-level timing for precise subtitles."""
    if not config.assembly_ai_api_key:
        raise RuntimeError("ASSEMBLY_AI_API_KEY is required when TRANSCRIPTION_PROVIDER=assemblyai")

    headers = {"authorization": config.assembly_ai_api_key}

    with open(video_path, "rb") as infile:
        upload_response = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers=headers,
            data=infile,
            timeout=300,
        )
    upload_response.raise_for_status()
    audio_url = upload_response.json().get("upload_url")
    if not audio_url:
        raise RuntimeError("AssemblyAI upload did not return upload_url")

    # Use configured transcription language
    target_language = config.transcription_language

    transcript_payload = {
        "audio_url": audio_url,
        "speaker_labels": True,
        "punctuate": True,
        "format_text": True,
        "speech_models": ["universal-2"],
    }

    # Set language code if not auto
    if target_language and target_language != "auto":
        # AssemblyAI uses specific language codes
        # Map our codes to AssemblyAI codes
        language_map = {
            "ms": "ms",  # Malay
            "id": "id",  # Indonesian
            "en": "en",  # English
            "th": "th",  # Thai
            "ja": "ja",  # Japanese
            "ko": "ko",  # Korean
            "zh": "zh",  # Chinese
            "es": "es",  # Spanish
            "fr": "fr",  # French
            "de": "de",  # German
        }

        aai_language = language_map.get(target_language, target_language)
        transcript_payload["language_code"] = aai_language
        logger.info(f"🌐 AssemblyAI transcription language set to: {aai_language} (Malay)")
    else:
        logger.info(f"🌐 Using auto-detect language")
    create_response = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers={**headers, "content-type": "application/json"},
        json=transcript_payload,
        timeout=120,
    )
    create_response.raise_for_status()
    transcript_id = create_response.json().get("id")
    if not transcript_id:
        raise RuntimeError("AssemblyAI transcript creation missing id")

    poll_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
    status = "queued"
    transcript_result: Dict[str, Any] = {}
    started = time.time()
    while status in {"queued", "processing"}:
        if time.time() - started > 1800:
            raise RuntimeError("AssemblyAI transcription timed out after 30 minutes")
        poll_response = requests.get(poll_url, headers=headers, timeout=60)
        poll_response.raise_for_status()
        transcript_result = poll_response.json()
        status = str(transcript_result.get("status", "")).lower()
        if status in {"queued", "processing"}:
            time.sleep(3)

    if status != "completed":
        error_text = transcript_result.get("error") or f"status={status}"
        logger.error("AssemblyAI transcription failed: %s", error_text)
        raise RuntimeError(f"Transcription failed: {error_text}")

    words_payload = transcript_result.get("words") or []
    words = [
        SimpleNamespace(
            text=str(word.get("text", "")).strip(),
            start=int(word.get("start", 0)),
            end=int(word.get("end", 0)),
            confidence=float(word.get("confidence", 1.0) or 1.0),
            speaker=word.get("speaker"),
        )
        for word in words_payload
        if str(word.get("text", "")).strip()
    ]

    utterances_payload = transcript_result.get("utterances") or []
    utterances = []
    if utterances_payload:
        for utterance in utterances_payload:
            u_start = int(utterance.get("start", 0))
            u_end = int(utterance.get("end", 0))
            u_words = [
                word
                for word in words
                if getattr(word, "start", 0) < u_end and getattr(word, "end", 0) > u_start
            ]
            utterances.append(
                SimpleNamespace(
                    text=str(utterance.get("text", "")).strip(),
                    start=u_start,
                    end=u_end,
                    speaker=utterance.get("speaker"),
                    words=u_words,
                )
            )

    transcript = SimpleNamespace(
        text=str(transcript_result.get("text", "")).strip(),
        words=words,
        utterances=utterances,
    )

    formatted_lines = format_transcript_for_analysis(transcript)
    cache_transcript_data(video_path, transcript)
    result = "\n".join(formatted_lines)
    logger.info(
        "AssemblyAI transcript formatted: %s segments, %s chars",
        len(formatted_lines),
        len(result),
    )
    return result


def get_video_transcript(video_path: Path, speech_model: str = "best") -> str:
    """Get transcript using configured provider (Google Gen AI or AssemblyAI)."""
    logger.info(f"Getting transcript for: {video_path} via {config.transcription_provider}")
    if config.transcription_provider == "assemblyai":
        return _get_video_transcript_assemblyai(video_path, speech_model)

    try:
        return _get_video_transcript_google_genai(video_path)
    except Exception as google_error:
        logger.error("Google Gen AI transcription failed: %s", google_error)
        if config.assembly_ai_api_key:
            logger.warning("Falling back to AssemblyAI transcription")
            return _get_video_transcript_assemblyai(video_path, speech_model)
        raise


def cache_transcript_data(video_path: Path, transcript) -> None:
    """Cache AssemblyAI transcript data for subtitle generation."""
    cache_path = video_path.with_suffix(".transcript_cache.json")

    words_data = []
    if transcript.words:
        words_data = [_serialize_transcript_word(word) for word in transcript.words]

    utterances_data = []
    if getattr(transcript, "utterances", None):
        utterances_data = [
            {
                "text": utterance.text,
                "start": utterance.start,
                "end": utterance.end,
                "speaker": getattr(utterance, "speaker", None),
                "words": [
                    _serialize_transcript_word(word)
                    for word in getattr(utterance, "words", []) or []
                ],
            }
            for utterance in transcript.utterances
        ]

    cache_data = {
        "version": TRANSCRIPT_CACHE_SCHEMA_VERSION,
        "words": words_data,
        "utterances": utterances_data,
        "text": transcript.text,
    }

    with open(cache_path, "w") as f:
        json.dump(cache_data, f)

    logger.info(f"Cached {len(words_data)} words to {cache_path}")


def load_cached_transcript_data(video_path: Path) -> Optional[Dict]:
    """Load cached AssemblyAI transcript data."""
    cache_path = video_path.with_suffix(".transcript_cache.json")

    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as f:
            payload = json.load(f)
            if "version" not in payload:
                payload["version"] = TRANSCRIPT_CACHE_SCHEMA_VERSION
                payload.setdefault("utterances", [])
            return payload
    except Exception as e:
        logger.warning(f"Failed to load transcript cache: {e}")
        return None


def _serialize_transcript_word(word) -> Dict[str, Any]:
    return {
        "text": word.text,
        "start": word.start,
        "end": word.end,
        "confidence": word.confidence if hasattr(word, "confidence") else 1.0,
        "speaker": getattr(word, "speaker", None),
    }


def format_transcript_for_analysis(transcript) -> List[str]:
    """Format transcripts into readable timestamped segments for AI analysis."""
    utterances = getattr(transcript, "utterances", None) or []
    if utterances:
        formatted_lines = []
        for utterance in utterances:
            start_time = format_ms_to_timestamp(utterance.start)
            end_time = format_ms_to_timestamp(utterance.end)
            speaker = getattr(utterance, "speaker", None)
            speaker_prefix = f"Speaker {speaker}: " if speaker else ""
            formatted_lines.append(
                f"[{start_time} - {end_time}] {speaker_prefix}{utterance.text}"
            )
        return formatted_lines

    formatted_lines = []
    words = getattr(transcript, "words", None) or []
    if not words:
        return formatted_lines

    logger.info(f"Processing {len(words)} words with precise timing")

    current_segment = []
    current_start = None
    segment_word_count = 0
    max_words_per_segment = 8

    for word in words:
        if current_start is None:
            current_start = word.start

        current_segment.append(word.text)
        segment_word_count += 1

        if (
            segment_word_count >= max_words_per_segment
            or word.text.endswith(".")
            or word.text.endswith("!")
            or word.text.endswith("?")
        ):
            if current_segment:
                start_time = format_ms_to_timestamp(current_start)
                end_time = format_ms_to_timestamp(word.end)
                text = " ".join(current_segment)
                formatted_lines.append(f"[{start_time} - {end_time}] {text}")

            current_segment = []
            current_start = None
            segment_word_count = 0

    if current_segment and current_start is not None:
        start_time = format_ms_to_timestamp(current_start)
        end_time = format_ms_to_timestamp(words[-1].end)
        text = " ".join(current_segment)
        formatted_lines.append(f"[{start_time} - {end_time}] {text}")

    return formatted_lines


def format_ms_to_timestamp(ms: int) -> str:
    """Format milliseconds to MM:SS format."""
    seconds = ms // 1000
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def round_to_even(value: int) -> int:
    """Round integer to nearest even number for H.264 compatibility."""
    return value - (value % 2)


def get_scaled_font_size(base_font_size: int, video_width: int) -> int:
    """Scale caption font size by output width with sensible bounds."""
    scaled_size = int(base_font_size * (video_width / 720))
    return max(24, min(64, scaled_size))


def get_subtitle_max_width(video_width: int) -> int:
    """Return max subtitle text width with horizontal safe margins."""
    horizontal_padding = max(40, int(video_width * 0.06))
    return max(200, video_width - (horizontal_padding * 2))


def get_safe_vertical_position(
    video_height: int, text_height: int, position_y: float
) -> int:
    """Return subtitle y position clamped inside a top/bottom safe area."""
    min_top_padding = max(40, int(video_height * 0.05))
    # Significantly increased bottom padding to prevent text cutoff
    min_bottom_padding = max(200, int(video_height * 0.15))

    # Add extra padding for descenders (30% of text height) - g, y, p, q, j
    descender_padding = int(text_height * 0.3)

    desired_y = int(video_height * position_y - text_height // 2)
    max_y = video_height - min_bottom_padding - text_height - descender_padding

    # Ensure we stay well above the bottom
    return max(min_top_padding, min(desired_y, max_y))


def detect_optimal_crop_region(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
) -> Tuple[int, int, int, int]:
    """Detect optimal crop region using improved face detection."""
    try:
        original_width, original_height = video_clip.size

        # Calculate target dimensions and ensure they're even
        if original_width / original_height > target_ratio:
            new_width = round_to_even(int(original_height * target_ratio))
            new_height = round_to_even(original_height)
        else:
            new_width = round_to_even(original_width)
            new_height = round_to_even(int(original_width / target_ratio))

        # Try improved face detection
        face_centers = detect_faces_in_clip(video_clip, start_time, end_time)

        # Calculate crop position
        if face_centers:
            # Use weighted average of face centers with temporal consistency
            total_weight = sum(
                area * confidence for _, _, area, confidence in face_centers
            )
            if total_weight > 0:
                weighted_x = (
                    sum(
                        x * area * confidence for x, y, area, confidence in face_centers
                    )
                    / total_weight
                )
                weighted_y = (
                    sum(
                        y * area * confidence for x, y, area, confidence in face_centers
                    )
                    / total_weight
                )

                # Add slight bias towards upper portion for better face framing
                weighted_y = max(0, weighted_y - new_height * 0.1)

                x_offset = max(
                    0, min(int(weighted_x - new_width // 2), original_width - new_width)
                )
                y_offset = max(
                    0,
                    min(
                        int(weighted_y - new_height // 2), original_height - new_height
                    ),
                )

                logger.info(
                    f"Face-centered crop: {len(face_centers)} faces detected with improved algorithm"
                )
            else:
                # Center crop
                x_offset = (
                    (original_width - new_width) // 2
                    if original_width > new_width
                    else 0
                )
                y_offset = (
                    (original_height - new_height) // 2
                    if original_height > new_height
                    else 0
                )
        else:
            # Center crop
            x_offset = (
                (original_width - new_width) // 2 if original_width > new_width else 0
            )
            y_offset = (
                (original_height - new_height) // 2
                if original_height > new_height
                else 0
            )
            logger.info("Using center crop (no faces detected)")

        # Ensure offsets are even too
        x_offset = round_to_even(x_offset)
        y_offset = round_to_even(y_offset)

        logger.info(
            f"Crop dimensions: {new_width}x{new_height} at offset ({x_offset}, {y_offset})"
        )
        return (x_offset, y_offset, new_width, new_height)

    except Exception as e:
        logger.error(f"Error in crop detection: {e}")
        # Fallback to center crop
        original_width, original_height = video_clip.size
        if original_width / original_height > target_ratio:
            new_width = round_to_even(int(original_height * target_ratio))
            new_height = round_to_even(original_height)
        else:
            new_width = round_to_even(original_width)
            new_height = round_to_even(int(original_width / target_ratio))

        x_offset = (
            round_to_even((original_width - new_width) // 2)
            if original_width > new_width
            else 0
        )
        y_offset = (
            round_to_even((original_height - new_height) // 2)
            if original_height > new_height
            else 0
        )

        return (x_offset, y_offset, new_width, new_height)


def apply_smart_crop_to_clip(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_smart_features: bool = True,
) -> VideoFileClip:
    """
    Apply smart cropping with blur background, stacking, and smooth transitions.

    Args:
        video_clip: Source video clip
        start_time: Start time in seconds
        end_time: End time in seconds
        target_ratio: Target aspect ratio (width/height)
        enable_smart_features: Enable smart cropping features (blur, stacking, etc.)

    Returns:
        Processed video clip with smart cropping applied
    """
    if not enable_smart_features:
        # Fallback to original crop behavior
        x_offset, y_offset, new_width, new_height = detect_optimal_crop_region(
            video_clip, start_time, end_time, target_ratio
        )
        return video_clip.cropped(
            x1=x_offset, y1=y_offset, x2=x_offset + new_width, y2=y_offset + new_height
        )

    try:
        logger.info("Applying smart crop with person detection...")

        # Analyze clip and decide strategy
        decision = analyze_clip_and_decide_strategy(
            video_clip, start_time, end_time, target_ratio
        )

        original_width, original_height = video_clip.size
        target_height = original_height
        if target_height % 2 != 0:
            target_height += 1
        target_width = int(target_height * target_ratio)
        if target_width % 2 != 0:
            target_width += 1

        strategy = decision.strategy
        logger.info(f"Using strategy: {strategy.value} for {decision.num_people} people")

        # Handle WIDE_SHOT strategy (3+ people: wide shot then stacking)
        if strategy == CropStrategy.WIDE_SHOT:
            wide_duration = decision.metadata.get("wide_duration", 2.0)
            clip_duration = end_time - start_time

            if clip_duration > wide_duration:
                # Split into wide shot + stacking with crossfade
                transition_duration = 0.5  # 0.5 second crossfade

                # Wide shot part (letterbox blur)
                wide_clip = video_clip.subclipped(start_time, start_time + wide_duration)

                def process_wide_frame(get_frame, t):
                    frame = get_frame(t)
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    result_bgr = apply_letterbox_blur(frame_bgr, target_width, target_height)
                    return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

                wide_processed = wide_clip.fl(process_wide_frame)
                wide_processed = wide_processed.with_fps(video_clip.fps)

                # Stacking part
                stack_start = start_time + wide_duration
                stack_clip = video_clip.subclipped(stack_start, end_time)

                def process_stack_frame(get_frame, t):
                    frame = get_frame(t)
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    result_bgr = create_stacking_layout(
                        frame_bgr,
                        decision.target_boxes,
                        target_width,
                        target_height,
                        decision.metadata.get("split_ratio", 0.5)
                    )
                    return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

                stack_processed = stack_clip.fl(process_stack_frame)
                stack_processed = stack_processed.with_fps(video_clip.fps)

                # Combine with crossfade
                from moviepy import concatenate_videoclips
                wide_with_fade = wide_processed.with_effects([CrossFadeOut(transition_duration)])
                stack_with_fade = stack_processed.with_effects([CrossFadeIn(transition_duration)])

                final_clip = concatenate_videoclips(
                    [wide_with_fade, stack_with_fade],
                    method="compose"
                )

                logger.info(
                    f"Created wide shot ({wide_duration}s) + stacking "
                    f"({clip_duration - wide_duration:.1f}s) with {transition_duration}s transition"
                )
                return final_clip
            else:
                # Clip too short, just use letterbox
                strategy = CropStrategy.LETTERBOX_BLUR

        # Apply the appropriate strategy
        if strategy == CropStrategy.TRACK:
            # Traditional tracking: crop to the target box
            if decision.target_boxes:
                target_box = decision.target_boxes[0]
                x1, y1, x2, y2 = target_box

                # Calculate crop box centered on target
                box_center_x = (x1 + x2) // 2
                box_center_y = (y1 + y2) // 2

                crop_x = max(0, min(box_center_x - target_width // 2, original_width - target_width))
                crop_y = max(0, min(box_center_y - target_height // 2, original_height - target_height))

                # Ensure even offsets
                crop_x = round_to_even(crop_x)
                crop_y = round_to_even(crop_y)

                logger.info(f"Tracking crop at ({crop_x}, {crop_y})")
                return video_clip.cropped(
                    x1=crop_x, y1=crop_y,
                    x2=crop_x + target_width, y2=crop_y + target_height
                )
            else:
                # No target, fallback to center crop
                crop_x = (original_width - target_width) // 2
                crop_y = (original_height - target_height) // 2
                return video_clip.cropped(
                    x1=crop_x, y1=crop_y,
                    x2=crop_x + target_width, y2=crop_y + target_height
                )

        elif strategy == CropStrategy.LETTERBOX_BLUR:
            # Apply blur background letterbox frame-by-frame
            def process_frame(get_frame, t):
                # Get frame at time t
                frame = get_frame(t)
                # Convert RGB (MoviePy) to BGR (OpenCV)
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                result_bgr = apply_letterbox_blur(frame_bgr, target_width, target_height)
                # Convert back to RGB
                return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

            logger.info("Applying letterbox with blur background")
            processed = video_clip.fl(process_frame)
            return processed.with_fps(video_clip.fps)

        elif strategy == CropStrategy.STACKING:
            # Apply stacking layout frame-by-frame
            def process_frame(get_frame, t):
                frame = get_frame(t)
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                result_bgr = create_stacking_layout(
                    frame_bgr,
                    decision.target_boxes,
                    target_width,
                    target_height,
                    decision.metadata.get("split_ratio", 0.5)
                )
                return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

            logger.info(f"Applying stacking layout (50:50 split)")
            processed = video_clip.fl(process_frame)
            return processed.with_fps(video_clip.fps)

        else:
            # Unknown strategy, fallback to center crop
            logger.warning(f"Unknown strategy {strategy}, using center crop")
            crop_x = (original_width - target_width) // 2
            crop_y = (original_height - target_height) // 2
            return video_clip.cropped(
                x1=crop_x, y1=crop_y,
                x2=crop_x + target_width, y2=crop_y + target_height
            )

    except Exception as e:
        logger.error(f"Smart crop failed: {e}, falling back to standard crop")
        # Fallback to original behavior
        x_offset, y_offset, new_width, new_height = detect_optimal_crop_region(
            video_clip, start_time, end_time, target_ratio
        )
        return video_clip.cropped(
            x1=x_offset, y1=y_offset, x2=x_offset + new_width, y2=y_offset + new_height
        )


def apply_smart_crop_with_ffmpeg(
    video_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_scene_detection: bool = True,
) -> bool:
    """
    Apply smart cropping using FFmpeg for better performance.

    This is much faster than MoviePy frame-by-frame processing!

    Args:
        video_path: Input video file
        output_path: Output video file
        start_time: Start time in seconds
        end_time: End time in seconds
        target_ratio: Target aspect ratio
        enable_scene_detection: Enable scene detection

    Returns:
        True if successful
    """
    import tempfile

    try:
        logger.info(f"FFmpeg-based smart crop: {start_time:.1f}s - {end_time:.1f}s")

        # Load video to analyze
        video_clip = VideoFileClip(str(video_path))
        original_width, original_height = video_clip.size

        # Calculate target dimensions
        target_height = original_height
        if target_height % 2 != 0:
            target_height += 1
        target_width = int(target_height * target_ratio)
        if target_width % 2 != 0:
            target_width += 1

        # Analyze clip and get strategies per scene
        scene_decisions = analyze_clip_with_scene_detection(
            video_clip, start_time, end_time, target_ratio, enable_scene_detection
        )

        video_clip.close()

        logger.info(f"Processing {len(scene_decisions)} scenes with FFmpeg")

        # Process each scene with FFmpeg
        scene_files = []
        temp_dir = Path(tempfile.gettempdir())

        for idx, (scene_start, scene_end, decision) in enumerate(scene_decisions):
            scene_file = temp_dir / f"scene_{idx}_{os.getpid()}.mp4"

            # Generate FFmpeg filter based on strategy
            strategy_name = decision.strategy.value
            logger.info(
                f"Scene {idx}: {scene_start:.1f}s-{scene_end:.1f}s strategy={strategy_name} "
                f"boxes={decision.target_boxes}"
            )

            filter_str = generate_crop_filter(
                strategy_name,
                decision.target_boxes,
                original_width,
                original_height,
                target_width,
                target_height
            )

            # Process scene with FFmpeg
            success = process_scene_with_ffmpeg(
                video_path,
                scene_file,
                scene_start,
                scene_end,
                filter_str,
                target_width,
                target_height
            )

            if success and scene_file.exists():
                scene_files.append(scene_file)
            else:
                logger.warning(f"Scene {idx} processing failed, skipping")

        if not scene_files:
            logger.error("No scenes were processed successfully")
            return False

        # Extract original audio with exact time range
        audio_file = temp_dir / f"audio_{os.getpid()}.aac"
        extract_audio_ffmpeg(video_path, audio_file, start_time, end_time)

        # Concatenate all scenes
        success = concat_scenes_with_ffmpeg(
            scene_files,
            output_path,
            audio_file if audio_file.exists() else None
        )

        # Cleanup temp files
        for scene_file in scene_files:
            try:
                scene_file.unlink()
            except:
                pass
        if audio_file.exists():
            try:
                audio_file.unlink()
            except:
                pass

        return success

    except Exception as e:
        logger.error(f"FFmpeg smart crop failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def apply_smart_crop_with_scenes(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_scene_detection: bool = True,
) -> VideoFileClip:
    """
    Apply smart cropping with automatic scene detection.
    Each scene can have different cropping strategy (blur, stacking, tracking).

    Args:
        video_clip: Source video clip
        start_time: Start time in seconds
        end_time: End time in seconds
        target_ratio: Target aspect ratio (width/height)
        enable_scene_detection: Enable automatic scene detection

    Returns:
        Processed video clip with scene-based smart cropping
    """
    try:
        logger.info(
            f"Applying scene-based smart crop: {start_time:.1f}s - {end_time:.1f}s "
            f"(scene_detection={enable_scene_detection})"
        )

        # Analyze clip and get strategy per scene
        scene_decisions = analyze_clip_with_scene_detection(
            video_clip, start_time, end_time, target_ratio, enable_scene_detection
        )

        if len(scene_decisions) == 1:
            # Only one scene, use simple processing
            scene_start, scene_end, decision = scene_decisions[0]
            return _process_scene_with_strategy(
                video_clip, scene_start, scene_end, decision, target_ratio
            )

        # Multiple scenes, process each and concatenate
        from moviepy import concatenate_videoclips

        processed_scenes = []
        for scene_start, scene_end, decision in scene_decisions:
            processed_scene = _process_scene_with_strategy(
                video_clip, scene_start, scene_end, decision, target_ratio
            )
            processed_scenes.append(processed_scene)

        # Concatenate all scenes
        final_clip = concatenate_videoclips(processed_scenes, method="compose")

        logger.info(
            f"Successfully processed {len(scene_decisions)} scenes with smart cropping"
        )

        return final_clip

    except Exception as e:
        logger.error(f"Scene-based smart crop failed: {e}, falling back to simple crop")
        import traceback
        traceback.print_exc()

        # Fallback to simple smart crop (no scene detection)
        return apply_smart_crop_to_clip(
            video_clip, start_time, end_time, target_ratio, enable_smart_features=True
        )


def _process_scene_with_strategy(
    video_clip: VideoFileClip,
    scene_start: float,
    scene_end: float,
    decision: "CropDecision",
    target_ratio: float,
) -> VideoFileClip:
    """
    Process a single scene with the given cropping strategy.

    Args:
        video_clip: Full video clip
        scene_start: Scene start time
        scene_end: Scene end time
        decision: CropDecision with strategy
        target_ratio: Target aspect ratio

    Returns:
        Processed scene clip
    """
    # Extract scene
    scene_clip = video_clip.subclipped(scene_start, scene_end)

    original_width, original_height = video_clip.size
    target_height = original_height
    if target_height % 2 != 0:
        target_height += 1
    target_width = int(target_height * target_ratio)
    if target_width % 2 != 0:
        target_width += 1

    strategy = decision.strategy

    # Apply strategy
    if strategy == CropStrategy.TRACK:
        # Crop to target box
        if decision.target_boxes:
            target_box = decision.target_boxes[0]
            x1, y1, x2, y2 = target_box

            box_center_x = (x1 + x2) // 2
            box_center_y = (y1 + y2) // 2

            crop_x = max(0, min(box_center_x - target_width // 2, original_width - target_width))
            crop_y = max(0, min(box_center_y - target_height // 2, original_height - target_height))

            crop_x = round_to_even(crop_x)
            crop_y = round_to_even(crop_y)

            return scene_clip.cropped(
                x1=crop_x, y1=crop_y,
                x2=crop_x + target_width, y2=crop_y + target_height
            )
        else:
            # Center crop
            crop_x = (original_width - target_width) // 2
            crop_y = (original_height - target_height) // 2
            return scene_clip.cropped(
                x1=crop_x, y1=crop_y,
                x2=crop_x + target_width, y2=crop_y + target_height
            )

    elif strategy == CropStrategy.LETTERBOX_BLUR:
        # Apply blur background frame-by-frame
        def process_frame(get_frame, t):
            frame = get_frame(t)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            result_bgr = apply_letterbox_blur(frame_bgr, target_width, target_height)
            return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

        return scene_clip.fl(process_frame).with_fps(scene_clip.fps)

    elif strategy == CropStrategy.STACKING:
        # Apply stacking layout frame-by-frame
        def process_frame(get_frame, t):
            frame = get_frame(t)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            result_bgr = create_stacking_layout(
                frame_bgr,
                decision.target_boxes,
                target_width,
                target_height,
                decision.metadata.get("split_ratio", 0.5)
            )
            return cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

        return scene_clip.fl(process_frame).with_fps(scene_clip.fps)

    else:
        # Fallback: center crop
        crop_x = (original_width - target_width) // 2
        crop_y = (original_height - target_height) // 2
        return scene_clip.cropped(
            x1=crop_x, y1=crop_y,
            x2=crop_x + target_width, y2=crop_y + target_height
        )


def detect_faces_in_clip(
    video_clip: VideoFileClip, start_time: float, end_time: float
) -> List[Tuple[int, int, int, float]]:
    """
    Improved face detection using multiple methods and temporal consistency.
    Returns list of (x, y, area, confidence) tuples.
    """
    face_centers = []

    try:
        # Try to use MediaPipe (most accurate)
        mp_face_detection = None
        try:
            import mediapipe as mp

            mp_face_detection = mp.solutions.face_detection.FaceDetection(
                model_selection=0,  # 0 for short-range (better for close faces)
                min_detection_confidence=0.5,
            )
            logger.info("Using MediaPipe face detector")
        except ImportError:
            logger.info("MediaPipe not available, falling back to OpenCV")
        except Exception as e:
            logger.warning(f"MediaPipe face detector failed to initialize: {e}")

        # Initialize OpenCV face detectors as fallback
        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        # Try to load DNN face detector (more accurate than Haar)
        dnn_net = None
        try:
            # Load OpenCV's DNN face detector
            prototxt_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector.pbtxt"
            )
            model_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector_uint8.pb"
            )

            # If DNN model files don't exist, we'll fall back to Haar cascade
            import os

            if os.path.exists(prototxt_path) and os.path.exists(model_path):
                dnn_net = cv2.dnn.readNetFromTensorflow(model_path, prototxt_path)
                logger.info("OpenCV DNN face detector loaded as backup")
            else:
                logger.info("OpenCV DNN face detector not available")
        except Exception:
            logger.info("OpenCV DNN face detector failed to load")

        # Sample more frames for better face detection (every 0.5 seconds)
        duration = end_time - start_time
        sample_interval = min(0.5, duration / 10)  # At least 10 samples, max every 0.5s
        sample_times = []

        current_time = start_time
        while current_time < end_time:
            sample_times.append(current_time)
            current_time += sample_interval

        # Ensure we always sample the middle and end
        if duration > 1.0:
            middle_time = start_time + duration / 2
            if middle_time not in sample_times:
                sample_times.append(middle_time)

        sample_times = [t for t in sample_times if t < end_time]
        logger.info(f"Sampling {len(sample_times)} frames for face detection")

        for sample_time in sample_times:
            try:
                frame = video_clip.get_frame(sample_time)
                height, width = frame.shape[:2]
                detected_faces = []

                # Try MediaPipe first (most accurate)
                if mp_face_detection is not None:
                    try:
                        # MediaPipe expects RGB format
                        results = mp_face_detection.process(frame)

                        if results.detections:
                            for detection in results.detections:
                                bbox = detection.location_data.relative_bounding_box
                                confidence = detection.score[0]

                                # Convert relative coordinates to absolute
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)

                                if w > 30 and h > 30:  # Minimum face size
                                    detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"MediaPipe detection failed for frame at {sample_time}s: {e}"
                        )

                # If MediaPipe didn't find faces, try DNN detector
                if not detected_faces and dnn_net is not None:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        blob = cv2.dnn.blobFromImage(
                            frame_bgr, 1.0, (300, 300), [104, 117, 123]
                        )
                        dnn_net.setInput(blob)
                        detections = dnn_net.forward()

                        for i in range(detections.shape[2]):
                            confidence = detections[0, 0, i, 2]
                            if confidence > 0.5:  # Confidence threshold
                                x1 = int(detections[0, 0, i, 3] * width)
                                y1 = int(detections[0, 0, i, 4] * height)
                                x2 = int(detections[0, 0, i, 5] * width)
                                y2 = int(detections[0, 0, i, 6] * height)

                                w = x2 - x1
                                h = y2 - y1

                                if w > 30 and h > 30:  # Minimum face size
                                    detected_faces.append((x1, y1, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"DNN detection failed for frame at {sample_time}s: {e}"
                        )

                # If still no faces found, use Haar cascade
                if not detected_faces:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

                        faces = haar_cascade.detectMultiScale(
                            gray,
                            scaleFactor=1.05,  # More sensitive
                            minNeighbors=3,  # Less strict
                            minSize=(40, 40),  # Smaller minimum size
                            maxSize=(
                                int(width * 0.7),
                                int(height * 0.7),
                            ),  # Maximum size limit
                        )

                        for x, y, w, h in faces:
                            # Estimate confidence based on face size and position
                            face_area = w * h
                            relative_size = face_area / (width * height)
                            confidence = min(
                                0.9, 0.3 + relative_size * 2
                            )  # Rough confidence estimate
                            detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"Haar cascade detection failed for frame at {sample_time}s: {e}"
                        )

                # Process detected faces
                for x, y, w, h, confidence in detected_faces:
                    face_center_x = x + w // 2
                    face_center_y = y + h // 2
                    face_area = w * h

                    # Filter out very small or very large faces
                    frame_area = width * height
                    relative_area = face_area / frame_area

                    if (
                        0.005 < relative_area < 0.3
                    ):  # Face should be 0.5% to 30% of frame
                        face_centers.append(
                            (face_center_x, face_center_y, face_area, confidence)
                        )

            except Exception as e:
                logger.warning(f"Error detecting faces in frame at {sample_time}s: {e}")
                continue

        # Close MediaPipe detector
        if mp_face_detection is not None:
            mp_face_detection.close()

        # Remove outliers (faces that are very far from the median position)
        if len(face_centers) > 2:
            face_centers = filter_face_outliers(face_centers)

        logger.info(f"Detected {len(face_centers)} reliable face centers")
        return face_centers

    except Exception as e:
        logger.error(f"Error in face detection: {e}")
        return []


def filter_face_outliers(
    face_centers: List[Tuple[int, int, int, float]],
) -> List[Tuple[int, int, int, float]]:
    """Remove face detections that are outliers (likely false positives)."""
    if len(face_centers) < 3:
        return face_centers

    try:
        # Calculate median position
        x_positions = [x for x, y, area, conf in face_centers]
        y_positions = [y for x, y, area, conf in face_centers]

        median_x = np.median(x_positions)
        median_y = np.median(y_positions)

        # Calculate standard deviation
        std_x = np.std(x_positions)
        std_y = np.std(y_positions)

        # Filter out faces that are more than 2 standard deviations away
        filtered_faces = []
        for face in face_centers:
            x, y, area, conf = face
            if abs(x - median_x) <= 2 * std_x and abs(y - median_y) <= 2 * std_y:
                filtered_faces.append(face)

        logger.info(
            f"Filtered {len(face_centers)} -> {len(filtered_faces)} faces (removed outliers)"
        )
        return (
            filtered_faces if filtered_faces else face_centers
        )  # Return original if all filtered

    except Exception as e:
        logger.warning(f"Error filtering face outliers: {e}")
        return face_centers


def parse_timestamp_to_seconds(timestamp_str: str) -> float:
    """Parse timestamp string to seconds."""
    try:
        timestamp_str = timestamp_str.strip()
        logger.info(f"Parsing timestamp: '{timestamp_str}'")  # Debug logging

        if ":" in timestamp_str:
            parts = timestamp_str.split(":")
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                result = minutes * 60 + seconds
                logger.info(f"Parsed '{timestamp_str}' -> {result}s")
                return result
            elif len(parts) == 3:  # HH:MM:SS format
                hours, minutes, seconds = map(int, parts)
                result = hours * 3600 + minutes * 60 + seconds
                logger.info(f"Parsed '{timestamp_str}' -> {result}s")
                return result

        # Try parsing as pure seconds
        result = float(timestamp_str)
        logger.info(f"Parsed '{timestamp_str}' as seconds -> {result}s")
        return result

    except (ValueError, IndexError) as e:
        logger.error(f"Failed to parse timestamp '{timestamp_str}': {e}")
        return 0.0


def get_words_in_range(
    transcript_data: Dict, clip_start: float, clip_end: float
) -> List[Dict]:
    """Extract words that fall within a clip timerange."""
    if not transcript_data or not transcript_data.get("words"):
        return []

    clip_start_ms = int(clip_start * 1000)
    clip_end_ms = int(clip_end * 1000)

    relevant_words = []
    for word_data in transcript_data["words"]:
        word_start = word_data["start"]
        word_end = word_data["end"]

        if word_start < clip_end_ms and word_end > clip_start_ms:
            relative_start = max(0, (word_start - clip_start_ms) / 1000.0)
            relative_end = min(
                (clip_end_ms - clip_start_ms) / 1000.0,
                (word_end - clip_start_ms) / 1000.0,
            )

            if relative_end > relative_start:
                relevant_words.append(
                    {
                        "text": word_data["text"],
                        "start": relative_start,
                        "end": relative_end,
                        "confidence": word_data.get("confidence", 1.0),
                    }
                )

    return relevant_words


def create_assemblyai_subtitles(
    video_path: Path,
    clip_start: float,
    clip_end: float,
    video_width: int,
    video_height: int,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
) -> List[TextClip]:
    """Create subtitles using AssemblyAI's precise word timing with template support."""
    transcript_data = load_cached_transcript_data(video_path)

    if not transcript_data or not transcript_data.get("words"):
        logger.warning("No cached transcript data available for subtitles")
        return []

    # Get template settings
    template = get_template(caption_template)
    animation_type = template.get("animation", "none")

    effective_font_family = font_family or template["font_family"]
    effective_font_size = int(font_size) if font_size else int(template["font_size"])
    effective_font_color = font_color or template["font_color"]
    effective_template = {
        **template,
        "font_size": effective_font_size,
        "font_color": effective_font_color,
        "font_family": effective_font_family,
    }

    logger.info(
        f"Creating subtitles with template '{caption_template}', animation: {animation_type}"
    )

    # Get words in range
    relevant_words = get_words_in_range(transcript_data, clip_start, clip_end)

    if not relevant_words:
        logger.warning("No words found in clip timerange")
        return []

    # Choose subtitle creation method based on animation type
    if animation_type == "karaoke":
        return create_karaoke_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    elif animation_type == "pop":
        return create_pop_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    elif animation_type == "fade":
        return create_fade_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    else:
        # Default static subtitles
        return create_static_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )


def create_static_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create standard static subtitles (original behavior)."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    max_text_width = get_subtitle_max_width(video_width)

    words_per_subtitle = 3
    for i in range(0, len(relevant_words), words_per_subtitle):
        word_group = relevant_words[i : i + words_per_subtitle]
        if not word_group:
            continue

        segment_start = word_group[0]["start"]
        segment_end = word_group[-1]["end"]
        segment_duration = segment_end - segment_start

        if segment_duration < 0.1:
            continue

        text = " ".join(word["text"] for word in word_group)

        try:
            stroke_color = template.get("stroke_color", "black")
            stroke_width = template.get("stroke_width", 1)

            text_clip = (
                TextClip(
                    text=text,
                    font=processor.font_path,
                    font_size=calculated_font_size,
                    color=template["font_color"],
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    method="caption",
                    size=(max_text_width, None),
                    text_align="center",
                    interline=10,  # Increased from 6 to prevent text cutoff
                )
                .with_duration(segment_duration)
                .with_start(segment_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create subtitle for '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} static subtitle elements")
    return subtitle_clips


def create_karaoke_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create karaoke-style subtitles with word-by-word highlighting."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    highlight_color = template.get("highlight_color", "#FFD700")
    normal_color = template["font_color"]
    max_text_width = get_subtitle_max_width(video_width)
    horizontal_padding = max(40, int(video_width * 0.06))

    words_per_group = 3

    def measure_word_group_width(word_group: List[Dict], font_size: int) -> List[int]:
        widths: List[int] = []
        for word in word_group:
            temp_clip = TextClip(
                text=word["text"],
                font=processor.font_path,
                font_size=font_size,
                color=normal_color,
                stroke_color=template.get("stroke_color", "black"),
                stroke_width=template.get("stroke_width", 1),
                method="label",
            )
            widths.append(temp_clip.size[0] if temp_clip.size else 50)
            temp_clip.close()
        return widths

    for group_idx in range(0, len(relevant_words), words_per_group):
        word_group = relevant_words[group_idx : group_idx + words_per_group]
        if not word_group:
            continue

        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]

        # For each word in the group, create a highlighted version
        for word_idx, current_word in enumerate(word_group):
            word_start = current_word["start"]
            word_end = current_word["end"]
            word_duration = word_end - word_start

            if word_duration < 0.05:
                continue

            try:
                # Build the text with the current word highlighted
                # We create individual text clips for each word and composite them
                word_clips_for_composite = []
                font_size_for_group = calculated_font_size
                word_widths = measure_word_group_width(word_group, font_size_for_group)
                space_width = font_size_for_group * 0.28
                total_width = sum(word_widths) + space_width * (len(word_group) - 1)

                if total_width > max_text_width and total_width > 0:
                    shrink_ratio = max_text_width / total_width
                    font_size_for_group = max(
                        20, int(font_size_for_group * shrink_ratio)
                    )
                    word_widths = measure_word_group_width(
                        word_group, font_size_for_group
                    )
                    space_width = font_size_for_group * 0.28
                    total_width = sum(word_widths) + space_width * (len(word_group) - 1)

                # Second pass: create positioned clips
                current_x = max(horizontal_padding, (video_width - total_width) / 2)
                text_height = 40

                for w_idx, word in enumerate(word_group):
                    is_current = w_idx == word_idx
                    color = highlight_color if is_current else normal_color
                    # Scale up current word slightly for pop effect
                    size_multiplier = 1.1 if is_current else 1.0

                    word_clip = (
                        TextClip(
                            text=word["text"],
                            font=processor.font_path,
                            font_size=int(font_size_for_group * size_multiplier),
                            color=color,
                            stroke_color=template.get("stroke_color", "black"),
                            stroke_width=template.get("stroke_width", 1),
                            method="label",
                        )
                        .with_duration(word_duration)
                        .with_start(word_start)
                    )

                    text_height = max(
                        text_height, word_clip.size[1] if word_clip.size else 40
                    )
                    vertical_position = get_safe_vertical_position(
                        video_height, text_height, position_y
                    )

                    word_clip = word_clip.with_position(
                        (int(current_x), vertical_position)
                    )
                    word_clips_for_composite.append(word_clip)

                    current_x += word_widths[w_idx] + space_width

                subtitle_clips.extend(word_clips_for_composite)

            except Exception as e:
                logger.warning(
                    f"Failed to create karaoke subtitle for word '{current_word['text']}': {e}"
                )
                continue

    logger.info(f"Created {len(subtitle_clips)} karaoke subtitle elements")
    return subtitle_clips


def create_pop_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create pop-style subtitles where each word pops in."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    max_text_width = get_subtitle_max_width(video_width)

    words_per_group = 3

    for group_idx in range(0, len(relevant_words), words_per_group):
        word_group = relevant_words[group_idx : group_idx + words_per_group]
        if not word_group:
            continue

        # Show the full group text
        group_text = " ".join(w["text"] for w in word_group)
        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]
        group_duration = group_end - group_start

        if group_duration < 0.1:
            continue

        try:
            # Create main text clip
            text_clip = (
                TextClip(
                    text=group_text,
                    font=processor.font_path,
                    font_size=calculated_font_size,
                    color=template["font_color"],
                    stroke_color=template.get("stroke_color", "black"),
                    stroke_width=template.get("stroke_width", 2),
                    method="caption",
                    size=(max_text_width, None),
                    text_align="center",
                    interline=10,  # Increased from 6 to prevent text cutoff
                )
                .with_duration(group_duration)
                .with_start(group_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create pop subtitle: {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} pop subtitle elements")
    return subtitle_clips


def create_fade_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create fade-style subtitles with smooth transitions."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    has_background = template.get("background", False)
    background_color = template.get("background_color", "#00000080")
    max_text_width = get_subtitle_max_width(video_width)

    words_per_group = 4

    for group_idx in range(0, len(relevant_words), words_per_group):
        word_group = relevant_words[group_idx : group_idx + words_per_group]
        if not word_group:
            continue

        group_text = " ".join(w["text"] for w in word_group)
        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]
        group_duration = group_end - group_start

        if group_duration < 0.1:
            continue

        try:
            # Create text clip
            text_clip = TextClip(
                text=group_text,
                font=processor.font_path,
                font_size=calculated_font_size,
                color=template["font_color"],
                stroke_color=template.get("stroke_color")
                if template.get("stroke_color")
                else None,
                stroke_width=template.get("stroke_width", 0),
                method="caption",
                size=(max_text_width, None),
                text_align="center",
                interline=10,  # Increased from 6 to prevent text cutoff
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            text_width = text_clip.size[0] if text_clip.size else 200
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )

            # Add background if specified
            if has_background and background_color:
                padding = 20  # Increased from 15 for better spacing
                # Parse background color (handle alpha)
                bg_color_hex = (
                    background_color[:7]
                    if len(background_color) > 7
                    else background_color
                )

                # Add extra vertical padding for descenders (increased to 35%)
                vertical_padding = padding + int(text_height * 0.35)

                bg_clip = (
                    ColorClip(
                        size=(text_width + padding * 2, text_height + vertical_padding),
                        color=tuple(
                            int(bg_color_hex[i : i + 2], 16) for i in (1, 3, 5)
                        ),
                    )
                    .with_duration(group_duration)
                    .with_start(group_start)
                )

                bg_clip = bg_clip.with_position(
                    ("center", vertical_position - vertical_padding // 2)
                )

                # Apply fade to background
                fade_duration = min(0.2, group_duration / 4)
                bg_clip = (
                    bg_clip.with_effects(
                        [CrossFadeIn(fade_duration), CrossFadeOut(fade_duration)]
                    )
                    if group_duration > 0.5
                    else bg_clip
                )

                subtitle_clips.append(bg_clip)

            # Apply timing and position to text
            text_clip = text_clip.with_duration(group_duration).with_start(group_start)
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create fade subtitle: {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} fade subtitle elements")
    return subtitle_clips


def create_optimized_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    add_subtitles: bool = True,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
) -> bool:
    """Create clip with optional subtitles. output_format: 'vertical' (9:16) or 'original' (keep source size)."""
    try:
        duration = end_time - start_time
        if duration <= 0:
            logger.error(f"Invalid clip duration: {duration:.1f}s")
            return False

        keep_original = output_format == "original"
        logger.info(
            f"Creating clip: {start_time:.1f}s - {end_time:.1f}s ({duration:.1f}s) "
            f"subtitles={add_subtitles} template '{caption_template}' format={'original' if keep_original else 'vertical'}"
        )

        # Fast path: no subtitles + original = ffmpeg stream copy (no re-encoding)
        if not add_subtitles and keep_original:
            import subprocess
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss", str(start_time),
                    "-i", str(video_path),
                    "-t", str(duration),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                logger.error(f"ffmpeg stream copy failed: {result.stderr}")
                return False
            logger.info(f"Successfully created clip (stream copy): {output_path}")
            return True

        # Load and process video
        video = VideoFileClip(str(video_path))

        if start_time >= video.duration:
            logger.error(
                f"Start time {start_time}s exceeds video duration {video.duration:.1f}s"
            )
            video.close()
            return False

        end_time = min(end_time, video.duration)
        clip = video.subclipped(start_time, end_time)

        if keep_original:
            # No face detection, no crop, no resize - use trimmed clip as-is
            processed_clip = clip
            target_width = round_to_even(processed_clip.w)
            target_height = round_to_even(processed_clip.h)
            if (target_width, target_height) != (processed_clip.w, processed_clip.h):
                processed_clip = processed_clip.resized((target_width, target_height))
            cropped_clip = None
        else:
            # Vertical 9:16: apply smart cropping with person detection & scene detection
            # Features: blur background, stacking, smooth transitions, per-scene strategies
            enable_smart = config.enable_smart_cropping

            if enable_smart:
                # Use FFmpeg-based smart cropping (MUCH FASTER!)
                import tempfile
                enable_scenes = config.enable_scene_detection

                # Create temp file for FFmpeg output
                temp_cropped = Path(tempfile.gettempdir()) / f"smart_crop_{os.getpid()}.mp4"

                logger.info("Using FFmpeg-based smart cropping (fast!)")

                # Process with FFmpeg
                success = apply_smart_crop_with_ffmpeg(
                    video_path,
                    temp_cropped,
                    start_time,
                    end_time,
                    target_ratio=9 / 16,
                    enable_scene_detection=enable_scenes
                )

                video.close()  # Close original video

                if success and temp_cropped.exists():
                    # Load FFmpeg output
                    cropped_clip = VideoFileClip(str(temp_cropped))
                    target_width = round_to_even(cropped_clip.w)
                    target_height = round_to_even(cropped_clip.h)
                    processed_clip = cropped_clip

                    # Note: temp file will be cleaned up after processing
                    logger.info(f"FFmpeg smart crop successful: {target_width}x{target_height}")
                else:
                    logger.error("FFmpeg smart crop failed, falling back to standard crop")
                    # Reload video and use standard crop
                    video = VideoFileClip(str(video_path))
                    clip = video.subclipped(start_time, end_time)
                    x_offset, y_offset, new_width, new_height = detect_optimal_crop_region(
                        video, start_time, end_time, target_ratio=9 / 16
                    )
                    cropped_clip = clip.cropped(
                        x1=x_offset, y1=y_offset, x2=x_offset + new_width, y2=y_offset + new_height
                    )
                    target_width = round_to_even(new_width)
                    target_height = round_to_even(new_height)
                    processed_clip = cropped_clip

            else:
                # Fallback to simple crop
                x_offset, y_offset, new_width, new_height = detect_optimal_crop_region(
                    video, start_time, end_time, target_ratio=9 / 16
                )
                cropped_clip = clip.cropped(
                    x1=x_offset, y1=y_offset, x2=x_offset + new_width, y2=y_offset + new_height
                )
                target_width = round_to_even(new_width)
                target_height = round_to_even(new_height)
                processed_clip = cropped_clip

        # Add AssemblyAI subtitles with template support
        final_clips = [processed_clip]

        if add_subtitles:
            subtitle_clips = create_assemblyai_subtitles(
                video_path,
                start_time,
                end_time,
                target_width,
                target_height,
                font_family,
                font_size,
                font_color,
                caption_template,
            )
            final_clips.extend(subtitle_clips)

        # Compose and encode
        final_clip = (
            CompositeVideoClip(final_clips) if len(final_clips) > 1 else processed_clip
        )
        source_fps = clip.fps if clip.fps and clip.fps > 0 else 30

        processor = VideoProcessor(font_family, font_size, font_color)
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile="temp-audio.m4a",
            remove_temp=True,
            logger=None,
            fps=source_fps,
            **encoding_settings,
        )

        # Cleanup
        if final_clip is not processed_clip:
            final_clip.close()
        if processed_clip is not cropped_clip:
            processed_clip.close()
        if cropped_clip is not None:
            cropped_clip.close()
        try:
            clip.close()
        except:
            pass
        try:
            video.close()
        except:
            pass

        # Cleanup temp FFmpeg file
        if 'temp_cropped' in locals() and temp_cropped.exists():
            try:
                temp_cropped.unlink()
                logger.info("Cleaned up temp FFmpeg file")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")

        logger.info(f"Successfully created clip: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to create clip: {e}")
        # Cleanup temp file on error
        if 'temp_cropped' in locals():
            try:
                Path(temp_cropped).unlink()
            except:
                pass
        return False


def create_clips_from_segments(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    add_subtitles: bool = True,
) -> List[Dict[str, Any]]:
    """Create optimized video clips from segments with template support."""
    logger.info(
        f"Creating {len(segments)} clips subtitles={add_subtitles} template '{caption_template}'"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    clips_info = []

    for i, segment in enumerate(segments):
        try:
            # Debug log the segment data
            logger.info(
                f"Processing segment {i + 1}: start='{segment.get('start_time')}', end='{segment.get('end_time')}'"
            )

            start_seconds = parse_timestamp_to_seconds(segment["start_time"])
            end_seconds = parse_timestamp_to_seconds(segment["end_time"])

            duration = end_seconds - start_seconds
            logger.info(
                f"Segment {i + 1} duration: {duration:.1f}s (start: {start_seconds}s, end: {end_seconds}s)"
            )

            if duration <= 0:
                logger.warning(
                    f"Skipping clip {i + 1}: invalid duration {duration:.1f}s (start: {start_seconds}s, end: {end_seconds}s)"
                )
                continue

            clip_filename = f"clip_{i + 1}_{segment['start_time'].replace(':', '')}-{segment['end_time'].replace(':', '')}.mp4"
            clip_path = output_dir / clip_filename

            success = create_optimized_clip(
                video_path,
                start_seconds,
                end_seconds,
                clip_path,
                add_subtitles,
                font_family,
                font_size,
                font_color,
                caption_template,
                output_format,
            )

            if success:
                clip_info = {
                    "clip_id": i + 1,
                    "filename": clip_filename,
                    "path": str(clip_path),
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                    "duration": duration,
                    "text": segment["text"],
                    "relevance_score": segment["relevance_score"],
                    "reasoning": segment["reasoning"],
                    # Include virality data if available
                    "virality_score": segment.get("virality_score", 0),
                    "hook_score": segment.get("hook_score", 0),
                    "engagement_score": segment.get("engagement_score", 0),
                    "value_score": segment.get("value_score", 0),
                    "shareability_score": segment.get("shareability_score", 0),
                    "hook_type": segment.get("hook_type"),
                }
                clips_info.append(clip_info)
                logger.info(f"Created clip {i + 1}: {duration:.1f}s")
            else:
                logger.error(f"Failed to create clip {i + 1}")

        except Exception as e:
            logger.error(f"Error processing clip {i + 1}: {e}")

    logger.info(f"Successfully created {len(clips_info)}/{len(segments)} clips")
    return clips_info


def get_available_transitions() -> List[str]:
    """Get list of available transition video files."""
    transitions_dir = Path(__file__).parent.parent / "transitions"
    if not transitions_dir.exists():
        logger.warning("Transitions directory not found")
        return []

    transition_files = []
    for file_path in transitions_dir.glob("*.mp4"):
        transition_files.append(str(file_path))

    logger.info(f"Found {len(transition_files)} transition files")
    return transition_files


def apply_transition_effect(
    clip1_path: Path, clip2_path: Path, transition_path: Path, output_path: Path
) -> bool:
    """Apply transition effect between two clips using a transition video."""
    clip1 = None
    clip2 = None
    transition = None
    clip1_tail = None
    clip2_intro = None
    clip2_remainder = None
    intro_segment = None
    final_clip = None

    try:
        from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips

        # Load clips
        clip1 = VideoFileClip(str(clip1_path))
        clip2 = VideoFileClip(str(clip2_path))
        transition = VideoFileClip(str(transition_path))

        # Keep the transition window within both clips so the output still matches
        # the current clip's duration and metadata.
        transition_duration = min(1.5, transition.duration, clip1.duration, clip2.duration)
        if transition_duration <= 0:
            logger.warning("Transition duration is zero, skipping transition effect")
            return False

        transition = transition.subclipped(0, transition_duration)

        # Resize transition to match clip dimensions
        clip_size = clip2.size
        transition = transition.resized(clip_size)

        # Build a transition intro from the previous clip tail over the first
        # part of the current clip so the exported file keeps clip2's duration.
        clip1_tail_start = max(0, clip1.duration - transition_duration)
        clip1_tail = clip1.subclipped(clip1_tail_start, clip1.duration).with_effects(
            [FadeOut(transition_duration)]
        )
        clip2_intro = clip2.subclipped(0, transition_duration).with_effects(
            [FadeIn(transition_duration)]
        )

        intro_segment = CompositeVideoClip(
            [clip1_tail, clip2_intro, transition], size=clip_size
        ).with_duration(transition_duration)
        if clip2_intro.audio is not None:
            intro_segment = intro_segment.with_audio(clip2_intro.audio)

        final_segments = [intro_segment]
        if clip2.duration > transition_duration:
            clip2_remainder = clip2.subclipped(transition_duration, clip2.duration)
            final_segments.append(clip2_remainder)

        final_clip = (
            concatenate_videoclips(final_segments, method="compose")
            if len(final_segments) > 1
            else intro_segment
        )

        # Write output
        processor = VideoProcessor()
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile="temp-audio.m4a",
            remove_temp=True,
            logger=None,
            **encoding_settings,
        )

        logger.info(f"Applied transition effect: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error applying transition effect: {e}")
        return False
    finally:
        for clip in (
            final_clip,
            intro_segment,
            clip2_remainder,
            clip2_intro,
            clip1_tail,
            transition,
            clip2,
            clip1,
        ):
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass


def create_clips_with_transitions(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    add_subtitles: bool = True,
) -> List[Dict[str, Any]]:
    """Create standalone video clips without inter-clip transitions.

    Kept as a backward-compatible wrapper for older call sites.
    """
    logger.info(
        f"Creating {len(segments)} standalone clips subtitles={add_subtitles} template '{caption_template}'"
    )
    logger.info(
        "Inter-clip transitions are disabled for standalone AI Shorts Gen exports"
    )
    return create_clips_from_segments(
        video_path,
        segments,
        output_dir,
        font_family,
        font_size,
        font_color,
        caption_template,
        output_format,
        add_subtitles,
    )


# Backward compatibility functions
def get_video_transcript_with_assemblyai(path: Path) -> str:
    """Backward compatibility wrapper."""
    return get_video_transcript(path)


def create_9_16_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    subtitle_text: str = "",
) -> bool:
    """Backward compatibility wrapper."""
    return create_optimized_clip(
        video_path, start_time, end_time, output_path, add_subtitles=bool(subtitle_text)
    )


# B-Roll compositing functions


def insert_broll_into_clip(
    main_clip_path: Path,
    broll_path: Path,
    insert_time: float,
    broll_duration: float,
    output_path: Path,
    transition_duration: float = 0.3,
) -> bool:
    """
    Insert B-roll footage into a clip at a specified timestamp.

    Args:
        main_clip_path: Path to the main video clip
        broll_path: Path to the B-roll video
        insert_time: When to insert B-roll (seconds from clip start)
        broll_duration: How long to show B-roll (seconds)
        output_path: Where to save the composited clip
        transition_duration: Crossfade duration (seconds)

    Returns:
        True if successful
    """
    try:
        from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips
        from moviepy.video.fx import CrossFadeIn, CrossFadeOut

        # Load clips
        main_clip = VideoFileClip(str(main_clip_path))
        broll_clip = VideoFileClip(str(broll_path))

        # Get main clip dimensions
        target_width, target_height = main_clip.size

        # Resize B-roll to match main clip (9:16 aspect ratio)
        broll_resized = resize_for_916(broll_clip, target_width, target_height)

        # Ensure B-roll doesn't exceed requested duration
        actual_broll_duration = min(broll_duration, broll_resized.duration)
        broll_trimmed = broll_resized.subclipped(0, actual_broll_duration)

        # Ensure insert_time is within clip bounds
        insert_time = max(0, min(insert_time, main_clip.duration - 0.5))

        # Calculate end time for B-roll
        broll_end_time = insert_time + actual_broll_duration

        # Don't let B-roll extend past the main clip
        if broll_end_time > main_clip.duration:
            broll_end_time = main_clip.duration
            actual_broll_duration = broll_end_time - insert_time
            broll_trimmed = broll_resized.subclipped(0, actual_broll_duration)

        # Split main clip into three parts
        part1 = main_clip.subclipped(0, insert_time) if insert_time > 0 else None
        part2_audio = main_clip.subclipped(insert_time, broll_end_time).audio
        part3 = (
            main_clip.subclipped(broll_end_time)
            if broll_end_time < main_clip.duration
            else None
        )

        # Apply crossfade to B-roll
        if transition_duration > 0:
            broll_with_audio = broll_trimmed.with_audio(part2_audio)
            broll_faded = broll_with_audio.with_effects(
                [CrossFadeIn(transition_duration), CrossFadeOut(transition_duration)]
            )
        else:
            broll_faded = broll_trimmed.with_audio(part2_audio)

        # Concatenate parts
        clips_to_concat = []
        if part1:
            clips_to_concat.append(part1)
        clips_to_concat.append(broll_faded)
        if part3:
            clips_to_concat.append(part3)

        if len(clips_to_concat) == 1:
            final_clip = clips_to_concat[0]
        else:
            final_clip = concatenate_videoclips(clips_to_concat, method="compose")

        # Write output
        processor = VideoProcessor()
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile="temp-audio-broll.m4a",
            remove_temp=True,
            logger=None,
            **encoding_settings,
        )

        # Cleanup
        final_clip.close()
        main_clip.close()
        broll_clip.close()
        broll_resized.close()

        logger.info(
            f"Inserted B-roll at {insert_time:.1f}s ({actual_broll_duration:.1f}s duration): {output_path}"
        )
        return True

    except Exception as e:
        logger.error(f"Error inserting B-roll: {e}")
        return False


def resize_for_916(
    clip: VideoFileClip, target_width: int, target_height: int
) -> VideoFileClip:
    """
    Resize a video clip to fit 9:16 aspect ratio with center crop.

    Args:
        clip: Input video clip
        target_width: Target width
        target_height: Target height

    Returns:
        Resized video clip
    """
    clip_width, clip_height = clip.size
    target_aspect = target_width / target_height
    clip_aspect = clip_width / clip_height

    if clip_aspect > target_aspect:
        # Clip is wider - scale to height and crop width
        scale_factor = target_height / clip_height
        new_width = int(clip_width * scale_factor)
        new_height = target_height
        resized = clip.resized((new_width, new_height))

        # Center crop
        x_offset = (new_width - target_width) // 2
        cropped = resized.cropped(x1=x_offset, x2=x_offset + target_width)
    else:
        # Clip is taller - scale to width and crop height
        scale_factor = target_width / clip_width
        new_width = target_width
        new_height = int(clip_height * scale_factor)
        resized = clip.resized((new_width, new_height))

        # Center crop (crop from top for portrait videos)
        y_offset = (new_height - target_height) // 4  # Bias towards top
        cropped = resized.cropped(y1=y_offset, y2=y_offset + target_height)

    return cropped


def apply_broll_to_clip(
    clip_path: Path, broll_suggestions: List[Dict[str, Any]], output_path: Path
) -> bool:
    """
    Apply multiple B-roll insertions to a clip.

    Args:
        clip_path: Path to the main clip
        broll_suggestions: List of B-roll suggestions with local_path, timestamp, duration
        output_path: Where to save the final clip

    Returns:
        True if successful
    """
    if not broll_suggestions:
        logger.info("No B-roll suggestions to apply")
        return False

    try:
        # Sort suggestions by timestamp (process from end to start to preserve timing)
        sorted_suggestions = sorted(
            broll_suggestions, key=lambda x: x.get("timestamp", 0), reverse=True
        )

        current_clip_path = clip_path
        temp_paths = []

        for i, suggestion in enumerate(sorted_suggestions):
            broll_path = suggestion.get("local_path")
            if not broll_path or not Path(broll_path).exists():
                logger.warning(f"B-roll file not found: {broll_path}")
                continue

            timestamp = suggestion.get("timestamp", 0)
            duration = suggestion.get("duration", 3.0)

            # Create temp output for intermediate clips
            if i < len(sorted_suggestions) - 1:
                temp_output = output_path.parent / f"temp_broll_{i}.mp4"
                temp_paths.append(temp_output)
            else:
                temp_output = output_path

            success = insert_broll_into_clip(
                current_clip_path, Path(broll_path), timestamp, duration, temp_output
            )

            if success:
                current_clip_path = temp_output
            else:
                logger.warning(f"Failed to insert B-roll at {timestamp}s")

        # Cleanup temp files
        for temp_path in temp_paths:
            if temp_path.exists() and temp_path != output_path:
                try:
                    temp_path.unlink()
                except Exception:
                    pass

        return True

    except Exception as e:
        logger.error(f"Error applying B-roll to clip: {e}")
        return False
