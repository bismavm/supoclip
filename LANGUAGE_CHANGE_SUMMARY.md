# 🌏 Language Change: Thailand → Malaysia

## Summary

Successfully changed all hardcoded language settings from **Thai (th)** to **Malay (ms)**.

---

## ✅ Files Changed

### 1. **`backend/src/config.py`**

**Line 31-32:**

**Before:**
```python
# HARDCODED: Always Thai
self.transcription_language = "th"  # HARDCODED THAI
```

**After:**
```python
# HARDCODED: Always Malay (Malaysia)
self.transcription_language = "ms"  # HARDCODED MALAY
```

---

### 2. **`backend/src/services/task_service.py`**

**Line 236:**

**Before:**
```python
segments_to_render = await VideoService.translate_segment_texts(
    segments_to_render, "th"  # HARDCODED THAI
)
```

**After:**
```python
segments_to_render = await VideoService.translate_segment_texts(
    segments_to_render, "ms"  # HARDCODED MALAY
)
```

---

### 3. **`backend/src/services/video_service.py`**

**Line 59 (Function signature):**

**Before:**
```python
def translate_text_sync(text: str, target_language: str = "th") -> str:
```

**After:**
```python
def translate_text_sync(text: str, target_language: str = "ms") -> str:
```

---

**Line 60 (Docstring):**

**Before:**
```python
"""HARDCODED: Translate to Thai using Gemini REST API."""
```

**After:**
```python
"""HARDCODED: Translate to Malay using Gemini REST API."""
```

---

**Line 69 (Log message):**

**Before:**
```python
logger.info(f"✅ API key found, translating to Thai...")
```

**After:**
```python
logger.info(f"✅ API key found, translating to Malay...")
```

---

**Lines 71-78 (Translation prompt):**

**Before:**
```python
prompt = f"""Translate this text to Thai (ภาษาไทย). Use Thai script.

Text: {text}

RULES:
- Output ONLY Thai text (ภาษาไทย)
- Use Thai characters
- NO English, NO explanations"""
```

**After:**
```python
prompt = f"""Translate this text to Malay (Bahasa Melayu). Use Malay language.

Text: {text}

RULES:
- Output ONLY Malay text (Bahasa Melayu)
- Use proper Malay spelling and grammar
- NO English, NO explanations"""
```

---

## 🔍 What Was NOT Changed

These remain **unchanged** (intentionally, as they are language support lists):

### `config.py` - Line 155-158:
```python
supported_languages = {
    "ms", "en", "id", "es", "fr", "de", "ja", "ko", "zh", "pt", "ru",
    "ar", "hi", "it", "nl", "pl", "tr", "vi", "th", "auto"
}
```
✅ **Correct** - This is a list of *supported* languages, not a hardcode.

---

### `api/routes/tasks.py` - Line 126:
```python
supported_languages = ["ms", "id", "en", "th", "ja", "ko", "zh", ...]
```
✅ **Correct** - API support list, not a hardcode.

---

### `video_utils.py` - Line 51:
```python
language_font_map = {
    "th": "NotoSansThai",      # Thai script
    "ja": "NotoSansJP",         # Japanese
    ...
}
```
✅ **Correct** - Font mapping for multi-language support.

---

### Language name dictionaries:
```python
SUPPORTED_LANGUAGES = {
    "ms": "Malay (Bahasa Melayu)",
    "id": "Indonesian (Bahasa Indonesia)",
    "en": "English",
    "th": "Thai (ภาษาไทย)",  # ← Not changed, it's a label
    ...
}
```
✅ **Correct** - These are display names, not hardcoded defaults.

---

## 🎯 Impact

### Before:
- Transcription language: **Thai (th)**
- Translation target: **Thai (ภาษาไทย)**
- Default for all processing: **Thai**

### After:
- Transcription language: **Malay (ms)**
- Translation target: **Malay (Bahasa Melayu)**
- Default for all processing: **Malay**

---

## ✅ Verification

All files compile successfully:
```bash
✅ config.py - No syntax errors
✅ services/task_service.py - No syntax errors  
✅ services/video_service.py - No syntax errors
```

---

## 🚀 Usage

No action needed! The changes are automatically applied.

All video processing will now:
- ✅ Transcribe audio in **Malay**
- ✅ Translate text to **Malay**
- ✅ Use Malay language models

---

## 🔄 Rollback Instructions

If you need to revert to Thai:

1. Change `config.py` line 32:
   ```python
   self.transcription_language = "th"
   ```

2. Change `task_service.py` line 236:
   ```python
   segments_to_render, "th"
   ```

3. Change `video_service.py` line 59:
   ```python
   target_language: str = "th"
   ```

4. Update prompts back to Thai in `video_service.py`

---

## 📝 Notes

- All language support lists remain **unchanged** (intentional)
- Font mappings remain **unchanged** (support multiple languages)
- API validation lists remain **unchanged** (multi-language support)
- Only **default/hardcoded values** were changed from `"th"` → `"ms"`

---

**Change completed successfully!** 🎉

All transcription and translation will now default to **Bahasa Melayu (Malaysia)**.
