# 🎬 Scene Detection Update

## Problem Yang Diselesaikan

### ❌ **SEBELUM:**
Smart cropping hanya apply **1 strategy per clip**:
```
Clip 1 (60 detik):
└─ LETTERBOX BLUR untuk semua 60 detik
   (Padahal ada 3 scene berbeda!)
```

### ✅ **SEKARANG:**
Smart cropping **dynamic per scene**:
```
Clip 1 (60 detik):
├─ Scene 1 (0-20s): 3 orang wide shot → LETTERBOX BLUR
├─ Scene 2 (20-40s): 2 orang conversation → STACKING
└─ Scene 3 (40-60s): 1 orang close-up → TRACK
```

---

## 🆕 Fitur Baru

### 1️⃣ **Automatic Scene Detection**
Deteksi scene changes otomatis berdasarkan frame differences:
- Threshold: 30.0 (adjustable)
- Min scene length: 2.0 seconds
- Sample interval: 0.5 seconds

### 2️⃣ **Per-Scene Strategy Selection**
Setiap scene dianalisis terpisah:
- Detect people count per scene
- Pick optimal strategy per scene
- Apply different strategies seamlessly

### 3️⃣ **Smart Concatenation**
Semua scene digabung smooth tanpa cut yang kasar.

---

## 🔧 Cara Kerja

### Scene Detection Algorithm:
```python
1. Sample frames every 0.5s dalam clip
2. Calculate frame difference antar frames
3. Normalize differences to 0-100 scale
4. Find scene boundaries (diff > threshold)
5. Ensure min scene length (2s)
6. Return list of scenes
```

### Per-Scene Processing:
```python
For each scene:
1. Subclip scene dari video
2. Detect people dalam scene
3. Decide strategy (TRACK/BLUR/STACKING)
4. Apply strategy ke scene
5. Concatenate semua scenes
```

---

## ⚙️ Configuration

### New Environment Variables:

#### **ENABLE_SCENE_DETECTION** (default: `true`)
```bash
# Enable scene detection
ENABLE_SCENE_DETECTION=true

# Disable untuk single strategy per clip
ENABLE_SCENE_DETECTION=false
```

#### **ENABLE_SMART_CROPPING** (existing)
```bash
# Master switch untuk smart features
ENABLE_SMART_CROPPING=true
```

### Kombinasi Settings:

| ENABLE_SMART_CROPPING | ENABLE_SCENE_DETECTION | Behavior |
|----------------------|------------------------|----------|
| `true` | `true` | ✅ Smart cropping + Scene detection (BEST) |
| `true` | `false` | Smart cropping, 1 strategy per clip |
| `false` | any | Legacy face-centered crop |

---

## 📊 Example Output

### Log dengan Scene Detection:
```
INFO - Analyzing clip with scene detection: 0.0s - 60.0s (scene_detection=True)
INFO - Detected 3 scenes in clip (0.0s - 60.0s)
INFO -   Scene 0.0s - 18.5s: letterbox_blur (3 people)
INFO -   Scene 18.5s - 42.0s: stacking (2 people)
INFO -   Scene 42.0s - 60.0s: track (1 people)
INFO - Successfully processed 3 scenes with smart cropping
```

### Video Output:
```
clip_1.mp4 (60s total):
├─ 0-18.5s: Wide shot dengan blur background
├─ 18.5-42s: Stacking 2 orang (split screen)
└─ 42-60s: Track 1 orang (face-centered)
```

---

## 🚀 How to Use

### 1. Update Code (Rebuild Docker):
```bash
# Stop containers
docker-compose down

# Rebuild backend & worker
docker-compose build backend worker

# Start
docker-compose up -d
```

### 2. Configure (Optional):
Edit `.env`:
```bash
ENABLE_SMART_CROPPING=true
ENABLE_SCENE_DETECTION=true
```

### 3. Test:
Upload video dengan multiple scenes dan lihat hasil!

---

## 📝 Files Changed

### ✅ New Functions Added:

#### `smart_cropping.py`:
- `detect_scene_changes()` - Detect scene boundaries
- `analyze_clip_with_scene_detection()` - Analyze per scene

#### `video_utils.py`:
- `apply_smart_crop_with_scenes()` - Main scene-based cropping
- `_process_scene_with_strategy()` - Process single scene

### ✅ Updated Files:
- `config.py` - Added `enable_scene_detection` config
- `docker-compose.yml` - Added `ENABLE_SCENE_DETECTION` env var
- `.env.example` - Documentation for new config

---

## 🎯 Customization

### Adjust Scene Detection Sensitivity:

In `smart_cropping.py` → `detect_scene_changes()`:

```python
# Default settings:
threshold = 30.0           # Scene change threshold (0-100)
min_scene_length = 2.0     # Minimum scene duration (seconds)
sample_interval = 0.5      # Frame sampling interval

# More sensitive (detect more scenes):
threshold = 20.0           # Lower = more sensitive
min_scene_length = 1.5     # Shorter minimum

# Less sensitive (fewer scenes):
threshold = 40.0           # Higher = less sensitive
min_scene_length = 3.0     # Longer minimum
```

### Disable Scene Detection for Short Clips:

In `smart_cropping.py` → `analyze_clip_with_scene_detection()`:

```python
# Default: disable for clips < 5 seconds
if not enable_scene_detection or (end_time - start_time) < 5.0:
    # No scene detection

# Change threshold:
if not enable_scene_detection or (end_time - start_time) < 10.0:
    # Disable for clips < 10 seconds
```

---

## 🐛 Troubleshooting

### Issue: Too Many Scenes Detected
**Symptom:** Video split into 10+ tiny scenes

**Solution:** Increase threshold
```python
# In smart_cropping.py
threshold = 40.0  # Default: 30.0
```

---

### Issue: Not Enough Scenes Detected
**Symptom:** Should be 3 scenes, only 1 detected

**Solution:** Decrease threshold
```python
# In smart_cropping.py
threshold = 20.0  # Default: 30.0
```

---

### Issue: Scene Detection Too Slow
**Symptom:** Processing takes very long

**Solution:** Reduce sample rate
```python
# In smart_cropping.py
sample_interval = 1.0  # Default: 0.5
num_samples = min(num_samples, 50)  # Default: 100
```

---

### Issue: Disable Scene Detection for Specific Clip

Set environment variable:
```bash
ENABLE_SCENE_DETECTION=false
```

Or in code, pass `enable_scene_detection=False`.

---

## ✅ Benefits

### Before Scene Detection:
❌ 1 clip = 1 strategy  
❌ Wide shots crushed to narrow crop  
❌ Close-ups wasted with letterbox  
❌ No adaptation to scene changes  

### After Scene Detection:
✅ Dynamic strategy per scene  
✅ Wide shots get blur letterbox  
✅ Close-ups get smart tracking  
✅ Conversations get stacking  
✅ Professional-looking output  

---

## 🎬 Example Scenarios

### Scenario 1: Interview
```
Video: 2-person interview (5 minutes)
├─ Intro (0-30s): Wide shot → LETTERBOX BLUR
├─ Q&A (30s-4m30s): Back-and-forth → STACKING
└─ Outro (4m30s-5m): Host solo → TRACK
```

### Scenario 2: Podcast
```
Video: 3-person podcast (10 minutes)
├─ Intro (0-1m): All 3 visible → LETTERBOX BLUR
├─ Discussion (1m-8m): Dynamic 2-person → STACKING
└─ Outro (8m-10m): Host solo → TRACK
```

### Scenario 3: Tutorial
```
Video: Solo tutorial (3 minutes)
├─ Scene 1 (0-1m): Person + screen → LETTERBOX BLUR
└─ Scene 2 (1m-3m): Close-up → TRACK
```

---

## 📚 API Reference

### `detect_scene_changes()`
```python
def detect_scene_changes(
    video_clip,
    start_time: float,
    end_time: float,
    threshold: float = 30.0,
    min_scene_length: float = 2.0
) -> List[Tuple[float, float]]
```

**Returns:** List of `(scene_start, scene_end)` tuples

---

### `analyze_clip_with_scene_detection()`
```python
def analyze_clip_with_scene_detection(
    video_clip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_scene_detection: bool = True
) -> List[Tuple[float, float, CropDecision]]
```

**Returns:** List of `(scene_start, scene_end, CropDecision)` tuples

---

### `apply_smart_crop_with_scenes()`
```python
def apply_smart_crop_with_scenes(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
    enable_scene_detection: bool = True,
) -> VideoFileClip
```

**Returns:** Processed VideoFileClip with scene-based strategies

---

## 🎉 Summary

**Scene detection membuat smart cropping jauh lebih powerful!**

Sekarang 1 clip bisa punya **multiple strategies** yang adapt per scene:
- Wide shots → Blur letterbox
- 2-person → Stacking
- 1-person → Tracking

**No more one-size-fits-all!** 🚀

---

## 🔄 Migration

### From Old Smart Cropping:
**No migration needed!** Scene detection is enabled by default but backward compatible.

To keep old behavior (1 strategy per clip):
```bash
ENABLE_SCENE_DETECTION=false
```

---

**Update selesai!** Rebuild Docker dan test! 🎬
