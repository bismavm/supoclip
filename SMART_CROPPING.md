# 🎯 Smart Cropping Features

Supoclip now includes intelligent cropping strategies that automatically adapt based on the number of people detected in each scene.

## ✨ Features

### 1. **Blur Background Letterbox** 
Instead of black bars, wide scenes now use a blurred version of the original frame as background.

**Before:**
```
┌─────────────┐
│  (black)    │
├─────────────┤
│   scene     │
├─────────────┤
│  (black)    │
└─────────────┘
```

**After:**
```
┌─────────────┐
│  (blur bg)  │
├─────────────┤
│   scene     │  ← Sharp original
├─────────────┤
│  (blur bg)  │
└─────────────┘
```

### 2. **Stacking Mode** (2 People Conversations)
For 2-person conversations, the video is split into a 50:50 stacked layout with each person in their own section.

```
┌─────────────┐
│  Person 1   │  ← Top half (zoomed)
├─────────────┤
│  Person 2   │  ← Bottom half (zoomed)
└─────────────┘
```

### 3. **Wide Shot → Stacking Transition** (3+ People)
When 3+ people are detected:
1. Shows a **wide shot** with blur background for 2 seconds (context)
2. Smoothly transitions to **stacking mode** (0.5s crossfade)
3. Focuses on the 2 main subjects (largest faces)

### 4. **Smart Tracking** (1 Person)
Automatically tracks and crops to a single person's face/body.

## 🎬 Cropping Strategy Flow

```
Scene Detection
    ↓
Person Count Analysis
    ↓
┌──────────────────────────────────────┐
│ 0 people  → Blur Letterbox           │
│ 1 person  → Track Face/Person        │
│ 2 people  → Stacking (50:50 split)   │
│ 3+ people → Wide Shot → Stacking     │
└──────────────────────────────────────┘
```

## 🔧 Configuration

### Enable/Disable Smart Cropping

Add to `.env` file:

```bash
# Enable smart cropping features (default: true)
ENABLE_SMART_CROPPING=true
```

### Technical Parameters

Default values (customizable in `smart_cropping.py`):

- **Wide shot duration**: 2.0 seconds
- **Transition duration**: 0.5 seconds (crossfade)
- **Blur intensity**: Gaussian blur sigma=50
- **Stacking split**: 50:50 ratio
- **Subject selection**: 2 people with largest faces
- **Frame samples**: 5 frames analyzed per clip

## 🧠 How It Works

### 1. Person Detection
Uses **YOLOv8** for person detection and **Haar Cascade** for face detection.

```python
from smart_cropping import detect_people_in_frame

# Detects people and their faces in each frame
detections = detect_people_in_frame(frame)
# Returns: List[PersonDetection(person_box, face_box, confidence, area)]
```

### 2. Strategy Decision
Analyzes sampled frames and decides optimal strategy:

```python
from smart_cropping import analyze_clip_and_decide_strategy

decision = analyze_clip_and_decide_strategy(
    video_clip, 
    start_time, 
    end_time,
    target_ratio=9/16
)
# Returns: CropDecision(strategy, target_boxes, num_people, metadata)
```

### 3. Frame Processing
Applies the chosen strategy frame-by-frame using MoviePy's `fl_image`:

```python
# Example: Blur letterbox
processed = video_clip.fl_image(
    lambda frame: apply_letterbox_blur(frame, width, height)
)
```

## 📦 Dependencies

Make sure these are installed:

```bash
pip install ultralytics  # YOLOv8 for person detection
pip install opencv-python  # Face detection + image processing
pip install moviepy  # Video processing
pip install numpy
```

## 🎨 Customization

### Adjust Blur Intensity

In `smart_cropping.py`:

```python
def apply_letterbox_blur(frame, target_width, target_height, blur_sigma=50):
    # Increase blur_sigma for more blur (default: 50)
    # Decrease for less blur
```

### Change Stacking Ratio

In `smart_cropping.py` → `decide_crop_strategy`:

```python
return CropDecision(
    strategy=CropStrategy.STACKING,
    target_boxes=boxes,
    num_people=2,
    metadata={"split_ratio": 0.5}  # Change to 0.4 for 40:60 split
)
```

### Modify Wide Shot Duration

In `smart_cropping.py` → `decide_crop_strategy`:

```python
metadata={
    "transition_to": CropStrategy.STACKING,
    "wide_duration": 2.0,  # Change duration here (seconds)
    "split_ratio": 0.5,
}
```

## 🐛 Troubleshooting

### YOLO Model Not Loading

```bash
# Download YOLOv8 nano model manually
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
# Place in project root or Python site-packages
```

### Fallback Behavior

If YOLO fails to load, the system automatically falls back to:
1. Haar Cascade face detection only
2. Estimate person boxes from face positions

### Performance Optimization

For faster processing (at cost of accuracy):

In `smart_cropping.py` → `analyze_clip_and_decide_strategy`:

```python
# Reduce frame samples
num_samples = 3  # Default: 5
```

## 📊 Performance Impact

| Strategy | Processing Speed | Memory Usage |
|----------|-----------------|--------------|
| Track | Fast (1x) | Low |
| Letterbox Blur | Medium (0.7x) | Medium |
| Stacking | Medium (0.7x) | Medium |
| Wide → Stack | Slow (0.5x) | High |

*Speed relative to standard crop (1x = no slowdown)*

## 🎯 Example Use Cases

### 1. Podcast Conversations
2 people talking → **Stacking mode** automatically splits screen

### 2. Group Interviews
3+ people → **Wide shot** for context, then **stacking** for main speakers

### 3. Solo Content
1 person → **Smart tracking** keeps face centered

### 4. B-roll / Scenery
No people detected → **Blur letterbox** for aesthetic framing

## 🔄 Migration from Old System

The new smart cropping is **backward compatible**. 

To disable and use old behavior:

```bash
ENABLE_SMART_CROPPING=false
```

Original `detect_optimal_crop_region` is still used as fallback if smart cropping fails.

## 📝 API Changes

### In `video_utils.py`

**New function added:**

```python
def apply_smart_crop_to_clip(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_smart_features: bool = True,
) -> VideoFileClip
```

**Updated function:**

```python
def create_optimized_clip(
    # ... existing params ...
    # Now uses apply_smart_crop_to_clip internally
    # Controlled by config.enable_smart_cropping
)
```

## 🚀 Future Enhancements

Potential improvements:

- [ ] Audio-based conversation detection for better stacking
- [ ] Dynamic split ratios based on person importance
- [ ] Multi-level stacking (3+ people in grid)
- [ ] Face tracking continuity across scene cuts
- [ ] Custom transition effects (slide, zoom, etc.)
- [ ] GPU acceleration for YOLO inference

## 📄 License

Same as parent project (Supoclip).

---

**Questions?** Check the main README or open an issue on GitHub.
