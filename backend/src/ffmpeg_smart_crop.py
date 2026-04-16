"""
FFmpeg-based smart cropping for better performance and reliability.

Uses FFmpeg for fast video processing instead of MoviePy frame-by-frame.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
import os

logger = logging.getLogger(__name__)


def generate_crop_filter(
    strategy: str,
    target_boxes: List[Tuple[int, int, int, int]],
    original_width: int,
    original_height: int,
    target_width: int,
    target_height: int,
) -> str:
    """
    Generate FFmpeg filter string for cropping strategy.

    Args:
        strategy: "track", "letterbox_blur", "stacking"
        target_boxes: List of bounding boxes
        original_width, original_height: Input dimensions
        target_width, target_height: Output dimensions

    Returns:
        FFmpeg filter string
    """
    if strategy == "track":
        # Crop and track target box
        if target_boxes:
            x1, y1, x2, y2 = target_boxes[0]
            box_center_x = (x1 + x2) // 2
            box_center_y = (y1 + y2) // 2

            crop_x = max(0, min(box_center_x - target_width // 2, original_width - target_width))
            crop_y = max(0, min(box_center_y - target_height // 2, original_height - target_height))

            # Ensure even numbers
            crop_x = crop_x - (crop_x % 2)
            crop_y = crop_y - (crop_y % 2)

            return f"crop={target_width}:{target_height}:{crop_x}:{crop_y}"
        else:
            # Center crop
            crop_x = (original_width - target_width) // 2
            crop_y = (original_height - target_height) // 2
            crop_x = crop_x - (crop_x % 2)
            crop_y = crop_y - (crop_y % 2)
            return f"crop={target_width}:{target_height}:{crop_x}:{crop_y}"

    elif strategy == "letterbox_blur":
        # Scale + blur background
        # 1. Create blur background (scale + blur)
        # 2. Overlay sharp scene in center
        scale_w = target_width
        scale_h = int(original_height * (target_width / original_width))

        # Complex filter: blur bg + sharp overlay
        filter_complex = (
            f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},"
            f"gblur=sigma=50[blurred];"
            f"[0:v]scale={scale_w}:{scale_h}[scaled];"
            f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
        )
        return filter_complex

    elif strategy == "stacking":
        # Split screen 50:50 (top/bottom)
        if len(target_boxes) < 2:
            # Fallback to letterbox
            return generate_crop_filter("letterbox_blur", target_boxes, original_width, original_height, target_width, target_height)

        half_height = target_height // 2

        # Get bounding boxes
        box1 = target_boxes[0]
        box2 = target_boxes[1]

        # Crop around each box
        x1, y1, x2, y2 = box1
        crop1_x = max(0, min((x1 + x2) // 2 - target_width // 2, original_width - target_width))
        crop1_y = max(0, min((y1 + y2) // 2 - half_height // 2, original_height - half_height))

        x1, y1, x2, y2 = box2
        crop2_x = max(0, min((x1 + x2) // 2 - target_width // 2, original_width - target_width))
        crop2_y = max(0, min((y1 + y2) // 2 - half_height // 2, original_height - half_height))

        # Ensure even
        crop1_x, crop1_y = crop1_x - (crop1_x % 2), crop1_y - (crop1_y % 2)
        crop2_x, crop2_y = crop2_x - (crop2_x % 2), crop2_y - (crop2_y % 2)

        # Complex filter: split and stack
        filter_complex = (
            f"[0:v]crop={target_width}:{half_height}:{crop1_x}:{crop1_y}[top];"
            f"[0:v]crop={target_width}:{half_height}:{crop2_x}:{crop2_y}[bottom];"
            f"[top][bottom]vstack"
        )
        return filter_complex

    else:
        # Default: center crop
        crop_x = (original_width - target_width) // 2
        crop_y = (original_height - target_height) // 2
        crop_x, crop_y = crop_x - (crop_x % 2), crop_y - (crop_y % 2)
        return f"crop={target_width}:{target_height}:{crop_x}:{crop_y}"


def process_scene_with_ffmpeg(
    input_video: Path,
    output_file: Path,
    start_time: float,
    end_time: float,
    filter_str: str,
    target_width: int,
    target_height: int,
) -> bool:
    """
    Process a single scene with FFmpeg.

    Args:
        input_video: Input video file
        output_file: Output file for this scene
        start_time: Start time in seconds
        end_time: End time in seconds
        filter_str: FFmpeg filter string
        target_width, target_height: Output dimensions

    Returns:
        True if successful
    """
    duration = end_time - start_time

    try:
        # Determine if filter is simple or complex
        if ";" in filter_str or "[" in filter_str:
            # Complex filter
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(input_video),
                "-t", str(duration),
                "-filter_complex", filter_str,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",  # No audio (we'll merge later)
                str(output_file)
            ]
        else:
            # Simple filter (crop only)
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(input_video),
                "-t", str(duration),
                "-vf", filter_str,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",  # No audio
                str(output_file)
            ]

        logger.info(f"Processing scene {start_time:.1f}s-{end_time:.1f}s with FFmpeg")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr}")
            return False

        logger.info(f"Scene processed successfully: {output_file}")
        return True

    except Exception as e:
        logger.error(f"Error processing scene with FFmpeg: {e}")
        return False


def concat_scenes_with_ffmpeg(
    scene_files: List[Path],
    output_file: Path,
    original_audio_file: Optional[Path] = None
) -> bool:
    """
    Concatenate scene files with FFmpeg.

    Args:
        scene_files: List of scene video files (no audio)
        output_file: Final output file
        original_audio_file: Optional audio track to merge

    Returns:
        True if successful
    """
    if not scene_files:
        logger.error("No scene files to concatenate")
        return False

    try:
        # Create concat demuxer file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            concat_file = f.name
            for scene_file in scene_files:
                # FFmpeg concat format requires absolute paths
                abs_path = Path(scene_file).absolute()
                f.write(f"file '{abs_path}'\n")

        logger.info(f"Concatenating {len(scene_files)} scenes with FFmpeg")

        # Concat video (no audio)
        temp_video = output_file.with_suffix('.temp.mp4')

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            str(temp_video)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg concat failed: {result.stderr}")
            os.unlink(concat_file)
            return False

        os.unlink(concat_file)

        # If audio provided, merge it
        if original_audio_file and original_audio_file.exists():
            logger.info("Merging original audio with concatenated video")

            cmd_merge = [
                "ffmpeg", "-y",
                "-i", str(temp_video),
                "-i", str(original_audio_file),
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(output_file)
            ]

            result = subprocess.run(cmd_merge, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                logger.error(f"FFmpeg audio merge failed: {result.stderr}")
                # Keep video without audio
                temp_video.rename(output_file)
            else:
                temp_video.unlink()
                logger.info("Audio merged successfully")
        else:
            # No audio, just rename temp to final
            temp_video.rename(output_file)
            logger.info("No audio to merge, video only")

        logger.info(f"Successfully concatenated scenes: {output_file}")
        return True

    except Exception as e:
        logger.error(f"Error concatenating scenes: {e}")
        return False


def extract_audio_ffmpeg(
    input_video: Path,
    output_audio: Path,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> bool:
    """
    Extract audio from video using FFmpeg with optional time range.

    Args:
        input_video: Input video file
        output_audio: Output audio file (AAC)
        start_time: Optional start time in seconds
        end_time: Optional end time in seconds

    Returns:
        True if successful
    """
    try:
        cmd = ["ffmpeg", "-y"]

        # Add time range if specified
        if start_time is not None:
            cmd.extend(["-ss", str(start_time)])

        cmd.extend(["-i", str(input_video)])

        if end_time is not None and start_time is not None:
            duration = end_time - start_time
            cmd.extend(["-t", str(duration)])

        cmd.extend([
            "-vn",  # No video
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_audio)
        ])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg audio extraction failed: {result.stderr}")
            return False

        logger.info(f"Audio extracted: {output_audio} ({start_time or 0:.1f}s - {end_time or 'end'}s)")
        return True

    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return False
