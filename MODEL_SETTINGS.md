# 🤖 Model Settings untuk Face & Person Tracking

## 📍 Lokasi Settings

Ada **2 sistem** untuk person/face detection:

### **1. Smart Cropping (NEW) - `smart_cropping.py`**
Untuk scene-based smart cropping dengan FFmpeg.

### **2. Legacy Face Detection - `video_utils.py`**  
Untuk standard face-centered crop (fallback).

---

## 🎯 Smart Cropping Models

**File:** `backend/src/smart_cropping.py`

### **Model 1: YOLOv8 (Person Detection)**

**Lokasi:** Line 51-62

```python
def get_yolo_model():
    """Lazy load YOLO model."""
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO('yolov8n.pt')  # ← MODEL SETTING
            logger.info("YOLO model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load YOLO model: {e}")
            _yolo_model = None
    return _yolo_model
```

**Setting:**
- **Model:** `yolov8n.pt` (YOLOv8 Nano)
- **Purpose:** Person detection
- **Class:** Detect class 0 (person)

**Available Models (bisa diganti):**
```python
# Dari tercepat → paling akurat:
YOLO('yolov8n.pt')  # Nano - fastest, least accurate
YOLO('yolov8s.pt')  # Small
YOLO('yolov8m.pt')  # Medium
YOLO('yolov8l.pt')  # Large
YOLO('yolov8x.pt')  # Extra Large - slowest, most accurate
```

---

### **Model 2: Haar Cascade (Face Detection)**

**Lokasi:** Line 65-77

```python
def get_face_cascade():
    """Lazy load Haar Cascade for face detection."""
    global _face_cascade
    if _face_cascade is None:
        try:
            _face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'  # ← MODEL
            )
            logger.info("Haar Cascade loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load Haar Cascade: {e}")
            _face_cascade = None
    return _face_cascade
```

**Setting:**
- **Model:** `haarcascade_frontalface_default.xml`
- **Purpose:** Face detection dalam person bounding box

**Parameters (Line 138-143):**
```python
faces = get_face_cascade().detectMultiScale(
    gray,
    scaleFactor=1.1,      # ← Scale factor (lower = more accurate, slower)
    minNeighbors=5,       # ← Min neighbors (higher = less false positives)
    minSize=(30, 30)      # ← Min face size in pixels
)
```

**Tuning Parameters:**
```python
# Lebih akurat tapi lambat:
scaleFactor=1.05      # More scales checked
minNeighbors=7        # Stricter detection

# Lebih cepat tapi kurang akurat:
scaleFactor=1.3       # Fewer scales
minNeighbors=3        # More lenient
```

---

## 🎯 Legacy Face Detection Models

**File:** `backend/src/video_utils.py`

Untuk standard face-centered crop (ketika smart cropping disabled).

### **Model 1: MediaPipe Face Detection (PRIMARY)**

**Lokasi:** Line 1525-1533

```python
import mediapipe as mp

mp_face_detection = mp.solutions.face_detection.FaceDetection(
    model_selection=0,              # ← MODEL SETTING
    min_detection_confidence=0.5,   # ← CONFIDENCE THRESHOLD
)
```

**Settings:**
- **Model:** `model_selection=0` (short-range model)
  - `0` = Short-range (best untuk close-up faces, 2 meters)
  - `1` = Full-range (untuk faces lebih jauh, 5 meters)
- **Confidence:** `0.5` (50% minimum confidence)

**Tuning:**
```python
# Untuk close-up faces (recommended):
model_selection=0
min_detection_confidence=0.5

# Untuk faces yang jauh:
model_selection=1
min_detection_confidence=0.3  # Lower threshold
```

---

### **Model 2: OpenCV DNN Face Detector (BACKUP)**

**Lokasi:** Line 1545-1565

```python
# Load OpenCV's DNN face detector
prototxt_path = cv2.data.haarcascades.replace(
    "haarcascades", "opencv_face_detector.pbtxt"
)
model_path = cv2.data.haarcascades.replace(
    "haarcascades", "opencv_face_detector_uint8.pb"
)

if os.path.exists(prototxt_path) and os.path.exists(model_path):
    dnn_net = cv2.dnn.readNetFromTensorflow(model_path, prototxt_path)
```

**Setting:**
- **Model:** OpenCV DNN (TensorFlow)
- **Files:** 
  - `opencv_face_detector.pbtxt`
  - `opencv_face_detector_uint8.pb`
- **Purpose:** Lebih akurat dari Haar Cascade

**Note:** Model ini optional (jika file tidak ada, fallback ke Haar).

---

### **Model 3: Haar Cascade (FALLBACK)**

**Lokasi:** Line 1540-1543

```python
haar_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
```

**Same settings as smart cropping Haar Cascade above.**

---

## 📊 Model Priority (Fallback Chain)

### **Smart Cropping:**
```
1. YOLOv8 (person detection)
   ↓ (if fails)
2. Haar Cascade (face detection only)
   ↓ (if fails)
3. No detection (center crop)
```

### **Legacy Detection:**
```
1. MediaPipe Face Detection
   ↓ (if fails)
2. OpenCV DNN Face Detector
   ↓ (if fails)
3. Haar Cascade
   ↓ (if fails)
4. Center crop
```

---

## ⚙️ Cara Mengubah Model Settings

### **1. Ganti YOLO Model (Person Detection)**

Edit `smart_cropping.py` line 57:

```python
# Current (fastest):
_yolo_model = YOLO('yolov8n.pt')

# Change to more accurate:
_yolo_model = YOLO('yolov8m.pt')  # Medium (balanced)
_yolo_model = YOLO('yolov8x.pt')  # Extra Large (most accurate)
```

---

### **2. Ganti Haar Cascade Parameters**

Edit `smart_cropping.py` line 138-143:

```python
# Current settings:
faces = cascade.detectMultiScale(
    gray,
    scaleFactor=1.1,      # ← Change to 1.05 for more accuracy
    minNeighbors=5,       # ← Change to 7 for stricter detection
    minSize=(30, 30)      # ← Change to (50, 50) for larger faces only
)
```

---

### **3. Ganti MediaPipe Model**

Edit `video_utils.py` line 1530-1533:

```python
# Current (short-range):
mp_face_detection = mp.solutions.face_detection.FaceDetection(
    model_selection=0,              # ← Change to 1 for full-range
    min_detection_confidence=0.5,   # ← Change to 0.3 for more detections
)

# For faces farther away:
mp_face_detection = mp.solutions.face_detection.FaceDetection(
    model_selection=1,              # Full-range model
    min_detection_confidence=0.3,   # Lower threshold
)
```

---

### **4. Adjust Frame Sampling**

Edit `video_utils.py` line 1569:

```python
# Current:
sample_interval = min(0.5, duration / 10)  # Sample every 0.5s

# More frequent sampling (more accurate):
sample_interval = min(0.25, duration / 20)  # Sample every 0.25s

# Less frequent (faster):
sample_interval = min(1.0, duration / 5)    # Sample every 1s
```

---

## 🎯 Recommended Settings by Use Case

### **1. Fast Processing (Default)**
```python
# smart_cropping.py:
YOLO('yolov8n.pt')                    # Nano model
scaleFactor=1.1, minNeighbors=5       # Standard Haar

# video_utils.py:
model_selection=0                      # Short-range MediaPipe
min_detection_confidence=0.5
sample_interval = 0.5                  # Every 0.5s
```

### **2. Accuracy (Slower)**
```python
# smart_cropping.py:
YOLO('yolov8m.pt')                    # Medium model
scaleFactor=1.05, minNeighbors=7      # Stricter Haar

# video_utils.py:
model_selection=0                      # Short-range MediaPipe
min_detection_confidence=0.3           # Lower threshold
sample_interval = 0.25                 # Every 0.25s
```

### **3. Far-away Faces**
```python
# video_utils.py:
model_selection=1                      # Full-range MediaPipe
min_detection_confidence=0.3
```

---

## 📝 Environment Variables (Future Enhancement)

Bisa ditambahkan di `.env` untuk konfigurasi tanpa edit code:

```bash
# Suggested additions:
YOLO_MODEL=yolov8n.pt                 # yolov8n/s/m/l/x
FACE_DETECTION_MODEL=mediapipe        # mediapipe/dnn/haar
MEDIAPIPE_MODEL_SELECTION=0           # 0=short-range, 1=full-range
MIN_FACE_CONFIDENCE=0.5               # 0.0-1.0
FACE_MIN_SIZE=30                      # Pixels
SAMPLE_INTERVAL=0.5                   # Seconds
```

**To implement:** Add to `config.py` dan read dalam model initialization.

---

## 🧪 Testing Different Models

Restart container setelah edit:

```bash
# Edit file
nano backend/src/smart_cropping.py

# Restart
docker-compose restart backend worker

# Test & check logs
docker-compose logs worker -f | grep "model\|detection\|YOLO"
```

---

## 📊 Model Comparison

| Model | Accuracy | Speed | Memory | Use Case |
|-------|----------|-------|--------|----------|
| **YOLOv8n** | ⭐⭐⭐ | ⚡⚡⚡ | 💾 | Default (fast) |
| **YOLOv8m** | ⭐⭐⭐⭐ | ⚡⚡ | 💾💾 | Balanced |
| **YOLOv8x** | ⭐⭐⭐⭐⭐ | ⚡ | 💾💾💾 | Best accuracy |
| **MediaPipe** | ⭐⭐⭐⭐ | ⚡⚡⚡ | 💾 | Face detection |
| **DNN** | ⭐⭐⭐⭐ | ⚡⚡ | 💾💾 | OpenCV backup |
| **Haar** | ⭐⭐ | ⚡⚡⚡ | 💾 | Fallback |

---

## 🎉 Summary

**Smart Cropping Models:**
- 📁 `smart_cropping.py` line 57: **YOLO model** (`yolov8n.pt`)
- 📁 `smart_cropping.py` line 72: **Haar Cascade** (face detection)
- 📁 `smart_cropping.py` line 138-143: **Haar parameters**

**Legacy Face Detection:**
- 📁 `video_utils.py` line 1530: **MediaPipe** (primary)
- 📁 `video_utils.py` line 1560: **DNN** (backup)
- 📁 `video_utils.py` line 1541: **Haar** (fallback)

**All settings dapat di-tune sesuai kebutuhan!** 🎯
