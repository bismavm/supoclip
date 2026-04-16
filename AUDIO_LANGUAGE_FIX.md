# 🔧 Audio Sync & Language Fix

## Problems Fixed

### 1️⃣ **Audio Tidak Match dengan Video**
**Symptom:** Setelah FFmpeg processing, audio tidak sync dengan video.

**Root Cause:**
```
FFmpeg process scenes terpisah:
- Scene 1: 0-20s
- Scene 2: 20-40s
- Scene 3: 40-60s

Audio extracted dari full video: 0-end
→ Tidak match dengan cropped scenes!
```

**Solution:**
Extract audio dengan **exact time range** yang sama dengan video crop:
```python
# Before:
extract_audio_ffmpeg(video_path, audio_file)
# Extracts entire audio (0 - end)

# After:
extract_audio_ffmpeg(video_path, audio_file, start_time, end_time)
# Extracts only the cropped portion (e.g., 2.0 - 32.0s)
```

---

### 2️⃣ **AssemblyAI Menggunakan Bahasa Lain (Bukan Malay)**
**Symptom:** AssemblyAI transcription tidak pakai bahasa Malay meskipun config sudah `ms`.

**Root Cause:**
```python
# Line 635 di video_utils.py:
logger.info(f"🌐 Using auto-detect (will translate to Thai after)")
# ❌ Hardcode Thai!

# Line 626-632:
transcript_payload = {
    "audio_url": audio_url,
    "speaker_labels": True,
    # ❌ Tidak ada language_code!
}
```

**Solution:**
1. Hapus hardcode "Thai"
2. Set `language_code` di AssemblyAI payload:

```python
# Use configured language
target_language = config.transcription_language

transcript_payload = {
    "audio_url": audio_url,
    "speaker_labels": True,
    "punctuate": True,
    "format_text": True,
    "speech_models": ["universal-2"],
}

# Set language code
if target_language and target_language != "auto":
    aai_language = language_map.get(target_language, target_language)
    transcript_payload["language_code"] = aai_language
    logger.info(f"🌐 AssemblyAI transcription language set to: {aai_language} (Malay)")
```

---

## Changes Made

### **File 1: `ffmpeg_smart_crop.py`**

#### Updated function: `extract_audio_ffmpeg()`

**Before:**
```python
def extract_audio_ffmpeg(input_video: Path, output_audio: Path) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vn", "-c:a", "aac",
        str(output_audio)
    ]
    # Always extracts full audio
```

**After:**
```python
def extract_audio_ffmpeg(
    input_video: Path,
    output_audio: Path,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> bool:
    cmd = ["ffmpeg", "-y"]

    # Add time range if specified
    if start_time is not None:
        cmd.extend(["-ss", str(start_time)])

    cmd.extend(["-i", str(input_video)])

    if end_time is not None and start_time is not None:
        duration = end_time - start_time
        cmd.extend(["-t", str(duration)])

    cmd.extend(["-vn", "-c:a", "aac", str(output_audio)])
    # Now extracts only the specified time range!
```

---

### **File 2: `video_utils.py`**

#### Change 1: Audio extraction with time range

**Line ~1307 (in `apply_smart_crop_with_ffmpeg`):**

**Before:**
```python
extract_audio_ffmpeg(video_path, audio_file)
```

**After:**
```python
extract_audio_ffmpeg(video_path, audio_file, start_time, end_time)
```

#### Change 2: AssemblyAI language setting

**Line ~626-658 (in `_get_video_transcript_assemblyai`):**

**Before:**
```python
transcript_payload = {
    "audio_url": audio_url,
    "speaker_labels": True,
    # No language_code
}

logger.info(f"🌐 Using auto-detect (will translate to Thai after)")
# ❌ Hardcode Thai
```

**After:**
```python
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
    # Map to AssemblyAI language codes
    language_map = {
        "ms": "ms",  # Malay
        "id": "id",  # Indonesian
        "en": "en",  # English
        # ... etc
    }

    aai_language = language_map.get(target_language, target_language)
    transcript_payload["language_code"] = aai_language
    logger.info(f"🌐 AssemblyAI transcription language set to: {aai_language} (Malay)")
else:
    logger.info(f"🌐 Using auto-detect language")
```

---

## Verification

### ✅ **Audio Sync:**

After fix, FFmpeg commands will extract audio with exact timing:

**Before:**
```bash
# Extract full audio
ffmpeg -i video.mp4 -vn -c:a aac audio.aac
# audio.aac: 0 - 120s (full video)

# But cropped video: 2 - 32s
# → Out of sync! ❌
```

**After:**
```bash
# Extract audio with exact time range
ffmpeg -ss 2.0 -i video.mp4 -t 30.0 -vn -c:a aac audio.aac
# audio.aac: 2 - 32s (matches video!)
# → In sync! ✅
```

---

### ✅ **AssemblyAI Language:**

**Check logs after upload:**

```bash
docker-compose logs worker -f | grep "AssemblyAI\|language"

# Expected:
# "🌐 AssemblyAI transcription language set to: ms (Malay)"
```

**AssemblyAI API payload:**
```json
{
  "audio_url": "...",
  "speaker_labels": true,
  "punctuate": true,
  "format_text": true,
  "speech_models": ["universal-2"],
  "language_code": "ms"  // ← Now included! ✅
}
```

---

## Testing Checklist

After restart:

- [ ] **Audio Sync:**
  - Upload video
  - Check if audio matches video timing
  - No lag atau desync

- [ ] **Language:**
  - Check logs for `"language set to: ms"`
  - Verify transcription is in Malay
  - Subtitles should be Malay

---

## Deployment

### **1. Restart Containers:**
```bash
docker-compose restart backend worker
```

### **2. Test Upload:**
Upload video baru dan verify:

```bash
# Check logs
docker-compose logs worker -f | grep "language\|audio"

# Expected logs:
# "Audio extracted: audio.aac (2.0s - 32.0s)"
# "🌐 AssemblyAI transcription language set to: ms (Malay)"
```

### **3. Verify Output:**
- Audio sync dengan video ✅
- Transcription dalam Bahasa Malay ✅
- Subtitles dalam Bahasa Malay ✅

---

## Related Fixes

### **Google GenAI Already Correct:**
Google GenAI transcription (line 552-571) already uses `config.transcription_language` correctly:

```python
if config.transcription_language != "auto":
    language_name = language_map.get(config.transcription_language, ...)
    prompt = f"You are transcribing audio in {language_name}. ..."
    # ✅ Already correct!
```

---

## Summary

| Issue | Root Cause | Fix | Status |
|-------|------------|-----|--------|
| **Audio not sync** | Extracted full audio but video cropped | Extract audio with time range | ✅ Fixed |
| **AssemblyAI wrong language** | No language_code in payload | Set language_code from config | ✅ Fixed |
| **Hardcode "Thai" in logs** | Old log message | Updated to use config language | ✅ Fixed |

---

## Impact

### Before:
```
❌ Audio: 0-120s (full video)
❌ Video: 2-32s (cropped)
→ Out of sync!

❌ AssemblyAI: auto-detect (random language)
❌ Config: ms (Malay)
→ Wrong language!
```

### After:
```
✅ Audio: 2-32s (matches crop)
✅ Video: 2-32s (cropped)
→ Perfect sync!

✅ AssemblyAI: language_code="ms"
✅ Config: ms (Malay)
→ Correct language!
```

---

**Both issues fixed!** Restart containers dan test! 🚀
