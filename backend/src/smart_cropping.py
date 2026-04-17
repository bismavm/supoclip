"""
Smart cropping strategies for vertical video with person detection.

Features:
- Blur background letterbox for wide scenes
- Stacking mode for 2+ person conversations
- Smooth transitions between strategies
- Wide shot before stacking for 3+ people
"""

import logging
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum
from dataclasses import dataclass
import numpy as np
import cv2

logger = logging.getLogger(__name__)

# Lazy-loaded models
_yolo_model = None
_face_cascade = None


class CropStrategy(Enum):
    """Available cropping strategies."""
    TRACK = "track"  # Track single person/face
    LETTERBOX_BLUR = "letterbox_blur"  # Blur background letterbox
    STACKING = "stacking"  # Split screen for 2+ people
    WIDE_SHOT = "wide_shot"  # Wide shot before stacking (for 3+)


@dataclass
class PersonDetection:
    """Data class for detected person."""
    person_box: Tuple[int, int, int, int]  # x1, y1, x2, y2
    face_box: Optional[Tuple[int, int, int, int]]  # x1, y1, x2, y2
    confidence: float
    area: int


@dataclass
class CropDecision:
    """Data class for cropping decision."""
    strategy: CropStrategy
    target_boxes: List[Tuple[int, int, int, int]]  # Boxes to track
    num_people: int
    metadata: Dict[str, Any]  # Extra info for processing


def get_yolo_model():
    """Lazy load YOLO model."""
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO('yolov8n.pt')
            logger.info("YOLO model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load YOLO model: {e}")
            _yolo_model = None
    return _yolo_model


def get_face_cascade():
    """Lazy load Haar Cascade for face detection."""
    global _face_cascade
    if _face_cascade is None:
        try:
            _face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            logger.info("Haar Cascade loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load Haar Cascade: {e}")
            _face_cascade = None
    return _face_cascade


def detect_people_in_frame(frame: np.ndarray) -> List[PersonDetection]:
    """
    Detect people and their faces in a frame.

    Args:
        frame: BGR image from OpenCV

    Returns:
        List of PersonDetection objects
    """
    detections = []
    model = get_yolo_model()

    if model is None:
        logger.warning("YOLO not available, falling back to face-only detection")
        return _fallback_face_detection(frame)

    try:
        # Run YOLO detection
        results = model([frame], verbose=False)

        frame_height, frame_width = frame.shape[:2]
        min_person_area = (frame_width * frame_height) * 0.01  # Minimum 1% of frame
        min_confidence = 0.5  # Minimum confidence threshold

        for result in results:
            boxes = result.boxes
            for box in boxes:
                # Only process person class (class 0)
                if box.cls[0] == 0:
                    x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
                    person_box = (x1, y1, x2, y2)
                    confidence = float(box.conf[0])

                    # Filter 1: Confidence threshold (reject low confidence)
                    if confidence < min_confidence:
                        logger.debug(f"Skipping low confidence detection: {confidence:.2f}")
                        continue

                    width = x2 - x1
                    height = y2 - y1
                    area = width * height

                    # Filter 2: Minimum size (reject small detections like posters)
                    if area < min_person_area:
                        logger.debug(f"Skipping small detection: {area} < {min_person_area:.0f}")
                        continue

                    # Filter 3: Aspect ratio (real people have height > width)
                    aspect_ratio = height / width if width > 0 else 0
                    if aspect_ratio < 0.8 or aspect_ratio > 5.0:  # Reject weird proportions
                        logger.debug(f"Skipping weird aspect ratio: {aspect_ratio:.2f}")
                        continue

                    # Try to detect face within person bounding box
                    face_box = _detect_face_in_roi(frame, x1, y1, x2, y2)

                    # Filter 4: Prefer detections with faces (real people have faces)
                    # We still accept no-face detections but lower their priority
                    effective_confidence = confidence if face_box else confidence * 0.7

                    detections.append(PersonDetection(
                        person_box=person_box,
                        face_box=face_box,
                        confidence=effective_confidence,
                        area=area
                    ))

        logger.info(f"Detected {len(detections)} people in frame (filtered from {len(boxes) if boxes else 0})")
        return detections

    except Exception as e:
        logger.error(f"Error in person detection: {e}")
        return []


def _detect_face_in_roi(
    frame: np.ndarray,
    x1: int, y1: int, x2: int, y2: int
) -> Optional[Tuple[int, int, int, int]]:
    """Detect face within a person's bounding box."""
    cascade = get_face_cascade()
    if cascade is None:
        return None

    try:
        # Extract person ROI
        person_roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(person_roi, cv2.COLOR_BGR2GRAY)

        # Detect faces with stricter parameters to avoid false positives
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=7,  # Increased from 5 (stricter, less false positives)
            minSize=(50, 50),  # Increased from (30, 30) - larger minimum face size
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        if len(faces) > 0:
            # Return largest face (converted to absolute coordinates)
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])

            # Additional validation: face should be in upper portion of person box
            person_height = y2 - y1
            face_center_y = fy + fh // 2
            if face_center_y > person_height * 0.7:  # Face too low (probably not real)
                logger.debug(f"Face position too low in person box, rejecting")
                return None

            return (x1 + fx, y1 + fy, x1 + fx + fw, y1 + fy + fh)

    except Exception as e:
        logger.debug(f"Face detection in ROI failed: {e}")

    return None


def _fallback_face_detection(frame: np.ndarray) -> List[PersonDetection]:
    """Fallback to face-only detection when YOLO is not available."""
    cascade = get_face_cascade()
    if cascade is None:
        return []

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_height, frame_width = frame.shape[:2]
        min_face_area = (frame_width * frame_height) * 0.005  # Minimum 0.5% of frame

        # Stricter parameters to reduce false positives
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=7,  # Increased from 5 for fewer false positives
            minSize=(60, 60),  # Increased from (50, 50)
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        detections = []
        for (x, y, w, h) in faces:
            face_area = w * h

            # Filter out small detections (likely false positives)
            if face_area < min_face_area:
                logger.debug(f"Skipping small face detection: {face_area} < {min_face_area:.0f}")
                continue

            face_box = (x, y, x + w, y + h)
            # Estimate person box as 3x height, 1.5x width centered on face
            person_h = h * 3
            person_w = int(w * 1.5)
            person_x = max(0, x - (person_w - w) // 2)
            person_y = max(0, y - int(h * 0.5))

            person_box = (person_x, person_y, person_x + person_w, person_y + person_h)
            area = person_w * person_h

            detections.append(PersonDetection(
                person_box=person_box,
                face_box=face_box,
                confidence=0.8,  # Default confidence for Haar
                area=area
            ))

        logger.info(f"Fallback detected {len(detections)} faces (filtered from {len(faces)})")
        return detections

    except Exception as e:
        logger.error(f"Fallback face detection failed: {e}")
        return []


def decide_crop_strategy(
    detections: List[PersonDetection],
    frame_width: int,
    frame_height: int,
    target_ratio: float = 9 / 16,
    wide_shot_threshold: float = 2.0,  # seconds to show wide shot for 3+
) -> CropDecision:
    """
    Decide the optimal cropping strategy based on detected people.

    Args:
        detections: List of PersonDetection objects
        frame_width: Original frame width
        frame_height: Original frame height
        target_ratio: Target aspect ratio (width/height)
        wide_shot_threshold: Duration for wide shot before stacking (3+ people)

    Returns:
        CropDecision with strategy and metadata
    """
    num_people = len(detections)
    max_width_for_crop = int(frame_height * target_ratio)

    # No people detected → blur letterbox
    if num_people == 0:
        logger.info("Strategy: LETTERBOX_BLUR (no people detected)")
        return CropDecision(
            strategy=CropStrategy.LETTERBOX_BLUR,
            target_boxes=[],
            num_people=0,
            metadata={"reason": "no_people"}
        )

    # 1 person → track face or person
    if num_people == 1:
        person = detections[0]
        target_box = person.face_box if person.face_box else person.person_box
        logger.info(
            f"Strategy: TRACK (1 person, tracking {'face' if person.face_box else 'person'}) "
            f"box={target_box}"
        )
        return CropDecision(
            strategy=CropStrategy.TRACK,
            target_boxes=[target_box],
            num_people=1,
            metadata={"tracking": "face" if person.face_box else "person"}
        )

    # 2 people → stacking mode
    if num_people == 2:
        # Sort by face size (largest first) or person size if no face
        sorted_detections = sorted(
            detections,
            key=lambda d: (d.face_box[2] - d.face_box[0]) * (d.face_box[3] - d.face_box[1])
                         if d.face_box else d.area,
            reverse=True
        )

        boxes = [
            d.face_box if d.face_box else d.person_box
            for d in sorted_detections[:2]
        ]

        logger.info("Strategy: STACKING (2 people conversation)")
        return CropDecision(
            strategy=CropStrategy.STACKING,
            target_boxes=boxes,
            num_people=2,
            metadata={"split_ratio": 0.5}  # 50:50 split
        )

    # 3+ people → wide shot with blur background
    logger.info(f"Strategy: LETTERBOX_BLUR ({num_people} people, wide shot)")
    return CropDecision(
        strategy=CropStrategy.LETTERBOX_BLUR,
        target_boxes=[],
        num_people=num_people,
        metadata={"reason": "wide_shot_multiple_people"}
    )


def _get_enclosing_box(boxes: List[Tuple[int, int, int, int]]) -> Tuple[int, int, int, int]:
    """Get bounding box that encloses all given boxes."""
    if not boxes:
        return (0, 0, 0, 0)

    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)

    return (min_x, min_y, max_x, max_y)


def create_blur_background(
    frame: np.ndarray,
    target_width: int,
    target_height: int,
    blur_sigma: int = 50
) -> np.ndarray:
    """
    Create a blurred background from the original frame.

    Args:
        frame: Original frame (BGR)
        target_width: Target width for output
        target_height: Target height for output
        blur_sigma: Gaussian blur sigma value

    Returns:
        Blurred background frame with target dimensions
    """
    try:
        # Resize frame to fill target dimensions (may stretch)
        bg = cv2.resize(frame, (target_width, target_height))

        # Apply Gaussian blur
        kernel_size = (blur_sigma * 2 + 1, blur_sigma * 2 + 1)
        blurred = cv2.GaussianBlur(bg, kernel_size, blur_sigma)

        # Darken slightly for better foreground contrast
        blurred = cv2.convertScaleAbs(blurred, alpha=0.7, beta=0)

        return blurred

    except Exception as e:
        logger.error(f"Error creating blur background: {e}")
        # Return black background as fallback
        return np.zeros((target_height, target_width, 3), dtype=np.uint8)


def apply_letterbox_blur(
    frame: np.ndarray,
    target_width: int,
    target_height: int,
    blur_sigma: int = 50
) -> np.ndarray:
    """
    Apply letterbox with blurred background instead of black bars.

    Args:
        frame: Original frame (BGR)
        target_width: Target width (9:16 ratio)
        target_height: Target height
        blur_sigma: Blur intensity

    Returns:
        Letterboxed frame with blur background
    """
    frame_h, frame_w = frame.shape[:2]

    # Create blurred background
    background = create_blur_background(frame, target_width, target_height, blur_sigma)

    # Scale original frame to fit width
    scale_factor = target_width / frame_w
    scaled_height = int(frame_h * scale_factor)
    scaled_frame = cv2.resize(frame, (target_width, scaled_height))

    # Center the scaled frame on the background
    y_offset = (target_height - scaled_height) // 2

    if y_offset >= 0:
        background[y_offset:y_offset + scaled_height, :] = scaled_frame
    else:
        # Frame taller than target, crop it
        crop_y = abs(y_offset)
        background[:, :] = scaled_frame[crop_y:crop_y + target_height, :]

    return background


def create_stacking_layout(
    frame: np.ndarray,
    target_boxes: List[Tuple[int, int, int, int]],
    target_width: int,
    target_height: int,
    split_ratio: float = 0.5
) -> np.ndarray:
    """
    Create split-screen stacking layout for 2 people.

    Args:
        frame: Original frame (BGR)
        target_boxes: List of 2 boxes to crop (person/face boxes)
        target_width: Target output width
        target_height: Target output height
        split_ratio: Ratio for split (0.5 = 50:50)

    Returns:
        Stacked frame with 2 crops
    """
    if len(target_boxes) < 2:
        logger.warning("Stacking requires 2 boxes, falling back to letterbox")
        return apply_letterbox_blur(frame, target_width, target_height)

    try:
        frame_h, frame_w = frame.shape[:2]

        # Calculate split heights
        top_height = int(target_height * split_ratio)
        bottom_height = target_height - top_height

        # Process top crop (person 1)
        box1 = target_boxes[0]
        crop1 = _crop_and_resize_for_stack(
            frame, box1, target_width, top_height, frame_w, frame_h
        )

        # Process bottom crop (person 2)
        box2 = target_boxes[1]
        crop2 = _crop_and_resize_for_stack(
            frame, box2, target_width, bottom_height, frame_w, frame_h
        )

        # Stack vertically
        stacked = np.vstack([crop1, crop2])

        return stacked

    except Exception as e:
        logger.error(f"Error creating stacking layout: {e}")
        return apply_letterbox_blur(frame, target_width, target_height)


def _crop_and_resize_for_stack(
    frame: np.ndarray,
    box: Tuple[int, int, int, int],
    target_width: int,
    target_height: int,
    frame_width: int,
    frame_height: int,
    padding: float = 0.2  # Add 20% padding around subject
) -> np.ndarray:
    """Crop around a box with padding and resize to target dimensions."""
    x1, y1, x2, y2 = box

    # Add padding
    box_w = x2 - x1
    box_h = y2 - y1
    pad_w = int(box_w * padding)
    pad_h = int(box_h * padding)

    # Expand box with padding, constrained to frame
    x1 = max(0, x1 - pad_w)
    y1 = max(0, y1 - pad_h)
    x2 = min(frame_width, x2 + pad_w)
    y2 = min(frame_height, y2 + pad_h)

    # Calculate crop dimensions to match target ratio
    crop_w = x2 - x1
    crop_h = y2 - y1
    target_ratio = target_width / target_height
    current_ratio = crop_w / crop_h if crop_h > 0 else 1

    # Adjust crop to match target ratio
    if current_ratio > target_ratio:
        # Too wide, crop width
        new_w = int(crop_h * target_ratio)
        diff = crop_w - new_w
        x1 += diff // 2
        x2 -= diff // 2
    else:
        # Too tall, crop height
        new_h = int(crop_w / target_ratio)
        diff = crop_h - new_h
        y1 += diff // 2
        y2 -= diff // 2

    # Ensure bounds
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(frame_width, x2)
    y2 = min(frame_height, y2)

    # Extract and resize crop
    crop = frame[y1:y2, x1:x2]

    if crop.size == 0:
        # Fallback to black if crop failed
        return np.zeros((target_height, target_width, 3), dtype=np.uint8)

    resized = cv2.resize(crop, (target_width, target_height))
    return resized


def sample_frames_for_analysis(
    video_clip,
    start_time: float,
    end_time: float,
    num_samples: int = 5
) -> List[np.ndarray]:
    """
    Sample frames from a video clip for analysis.

    Args:
        video_clip: MoviePy VideoFileClip
        start_time: Start time in seconds
        end_time: End time in seconds
        num_samples: Number of frames to sample

    Returns:
        List of frames as numpy arrays (RGB from MoviePy)
    """
    frames = []
    duration = end_time - start_time

    if duration <= 0:
        return frames

    # Sample frames evenly across the clip
    for i in range(num_samples):
        t = start_time + (duration * i / (num_samples - 1)) if num_samples > 1 else start_time
        t = min(t, end_time - 0.01)  # Avoid exact end time

        try:
            frame = video_clip.get_frame(t)
            # Convert RGB (MoviePy) to BGR (OpenCV)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            frames.append(frame_bgr)
        except Exception as e:
            logger.debug(f"Failed to get frame at {t}s: {e}")

    return frames


def analyze_clip_and_decide_strategy(
    video_clip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    num_samples: int = 5
) -> CropDecision:
    """
    Analyze a video clip and decide the best cropping strategy.

    Args:
        video_clip: MoviePy VideoFileClip
        start_time: Start time in seconds
        end_time: End time in seconds
        target_ratio: Target aspect ratio (width/height)
        num_samples: Number of frames to sample for analysis

    Returns:
        CropDecision with recommended strategy
    """
    logger.info(f"Analyzing clip {start_time:.1f}s - {end_time:.1f}s")

    frame_width, frame_height = video_clip.size

    # Sample frames
    frames = sample_frames_for_analysis(video_clip, start_time, end_time, num_samples)

    if not frames:
        logger.warning("No frames sampled, using letterbox blur")
        return CropDecision(
            strategy=CropStrategy.LETTERBOX_BLUR,
            target_boxes=[],
            num_people=0,
            metadata={"reason": "no_frames"}
        )

    # Detect people in each frame and aggregate results
    all_detections = []
    for frame in frames:
        detections = detect_people_in_frame(frame)
        all_detections.append(detections)

    # Use median number of people detected
    people_counts = [len(d) for d in all_detections]
    median_count = int(np.median(people_counts)) if people_counts else 0

    # Use detections from middle frame (most representative)
    middle_idx = len(all_detections) // 2
    representative_detections = all_detections[middle_idx] if all_detections else []

    # Filter to match median count (remove outliers)
    if len(representative_detections) > median_count:
        # Keep largest detections
        representative_detections = sorted(
            representative_detections,
            key=lambda d: d.area,
            reverse=True
        )[:median_count]

    # Decide strategy
    decision = decide_crop_strategy(
        representative_detections,
        frame_width,
        frame_height,
        target_ratio
    )

    logger.info(
        f"Decision: {decision.strategy.value} with {decision.num_people} people "
        f"(samples: {people_counts})"
    )

    return decision


def detect_scene_changes(
    video_clip,
    start_time: float,
    end_time: float,
    threshold: float = 30.0,
    min_scene_length: float = 2.0
) -> List[Tuple[float, float]]:
    """
    Detect scene changes within a clip using frame difference.

    Args:
        video_clip: MoviePy VideoFileClip
        start_time: Start time in seconds
        end_time: End time in seconds
        threshold: Threshold for scene change detection (0-100, higher = less sensitive)
        min_scene_length: Minimum scene length in seconds

    Returns:
        List of (scene_start, scene_end) tuples in seconds
    """
    import numpy as np

    duration = end_time - start_time
    if duration <= min_scene_length:
        # Too short to have multiple scenes
        return [(start_time, end_time)]

    # Sample frames for scene detection (1 frame per 0.5 seconds)
    sample_interval = 0.5
    num_samples = int(duration / sample_interval)
    num_samples = min(num_samples, 100)  # Cap at 100 samples

    if num_samples < 2:
        return [(start_time, end_time)]

    times = [start_time + (i * duration / num_samples) for i in range(num_samples)]

    # Get frame differences
    prev_frame = None
    frame_diffs = []
    frame_times = []

    for t in times:
        try:
            frame = video_clip.get_frame(t)

            if prev_frame is not None:
                # Calculate mean absolute difference
                diff = np.mean(np.abs(frame.astype(float) - prev_frame.astype(float)))
                frame_diffs.append(diff)
                frame_times.append(t)

            prev_frame = frame
        except Exception as e:
            logger.debug(f"Failed to get frame at {t}s: {e}")
            continue

    if not frame_diffs:
        return [(start_time, end_time)]

    # Normalize differences to 0-100 scale
    max_diff = max(frame_diffs) if frame_diffs else 1
    normalized_diffs = [(d / max_diff * 100) if max_diff > 0 else 0 for d in frame_diffs]

    # Find scene boundaries
    scene_boundaries = [start_time]

    for i, (diff, t) in enumerate(zip(normalized_diffs, frame_times)):
        if diff > threshold:
            # Potential scene change
            last_boundary = scene_boundaries[-1]
            if t - last_boundary >= min_scene_length:
                scene_boundaries.append(t)

    # Add end time
    if scene_boundaries[-1] != end_time:
        scene_boundaries.append(end_time)

    # Create scene pairs
    scenes = []
    for i in range(len(scene_boundaries) - 1):
        scenes.append((scene_boundaries[i], scene_boundaries[i + 1]))

    logger.info(f"Detected {len(scenes)} scenes in clip ({start_time:.1f}s - {end_time:.1f}s)")

    return scenes


def analyze_clip_with_scene_detection(
    video_clip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_scene_detection: bool = True
) -> List[Tuple[float, float, CropDecision]]:
    """
    Analyze clip and detect scenes, returning strategy per scene.

    Args:
        video_clip: MoviePy VideoFileClip
        start_time: Start time in seconds
        end_time: End time in seconds
        target_ratio: Target aspect ratio
        enable_scene_detection: Enable automatic scene detection

    Returns:
        List of (scene_start, scene_end, CropDecision) tuples
    """
    logger.info(
        f"Analyzing clip with scene detection: {start_time:.1f}s - {end_time:.1f}s "
        f"(scene_detection={enable_scene_detection})"
    )

    if not enable_scene_detection or (end_time - start_time) < 5.0:
        # No scene detection for short clips
        decision = analyze_clip_and_decide_strategy(
            video_clip, start_time, end_time, target_ratio
        )
        return [(start_time, end_time, decision)]

    # Detect scenes
    scenes = detect_scene_changes(video_clip, start_time, end_time)

    # Analyze each scene
    scene_decisions = []
    for scene_start, scene_end in scenes:
        decision = analyze_clip_and_decide_strategy(
            video_clip, scene_start, scene_end, target_ratio, num_samples=3
        )
        scene_decisions.append((scene_start, scene_end, decision))

        logger.info(
            f"  Scene {scene_start:.1f}s - {scene_end:.1f}s: "
            f"{decision.strategy.value} ({decision.num_people} people)"
        )

    return scene_decisions
