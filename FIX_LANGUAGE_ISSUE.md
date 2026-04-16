# 🔧 Fix: Masih Translate ke Bahasa Thailand

## 🔍 Root Cause

Meskipun code sudah diubah dari Thai → Malay, **user yang sudah ada di database** masih punya setting `default_language = "th"`.

### Kenapa Terjadi?
```
1. User dibuat sebelum code update → default_language = "th"
2. Code diupdate (th → ms)
3. User lama masih pakai setting lama di database
4. Translation tetap pakai "th" 😞
```

---

## ✅ Solusi

Update database untuk ubah semua user dari `"th"` → `"ms"`.

---

## 🚀 Quick Fix (Windows)

### **Option 1: Automatic Script (Recommended)**

Double-click file ini:
```
update_language.bat
```

Atau jalankan via command line:
```bash
cd C:\Users\Bisma\Desktop\PS_Demo\supoclip-dev\supoclip
update_language.bat
```

---

### **Option 2: Manual SQL (Advanced)**

Jalankan di terminal:

```bash
# 1. Masuk ke database
docker-compose exec postgres psql -U supoclip -d supoclip

# 2. Update semua user
UPDATE "user" SET default_language = 'ms' WHERE default_language = 'th';

# 3. Verify
SELECT default_language, COUNT(*) FROM "user" GROUP BY default_language;

# Expected output:
#  default_language | count
# ------------------+-------
#  ms               |     X

# 4. Exit
\q
```

---

## 🧪 Verification

### **1. Check Database:**
```bash
docker-compose exec postgres psql -U supoclip -d supoclip -c "SELECT default_language, COUNT(*) FROM \"user\" GROUP BY default_language;"
```

**Expected:** Semua user punya `default_language = 'ms'`

### **2. Check Logs:**
```bash
docker-compose logs worker -f | grep "LANGUAGE MODE"
```

**Expected:**
```
"LANGUAGE MODE ACTIVE: Forcing ms language in segment.text"
```

**Bukan lagi `th`!**

### **3. Test Upload Video Baru:**
Upload video dan cek apakah subtitle/translation pakai Bahasa Melayu.

---

## 🔍 Debug Commands

### **Check User Language Settings:**
```bash
docker-compose exec postgres psql -U supoclip -d supoclip -c "SELECT id, email, default_language FROM \"user\";"
```

### **Check Recent Tasks:**
```bash
docker-compose exec postgres psql -U supoclip -d supoclip -c "SELECT id, created_at, status FROM task ORDER BY created_at DESC LIMIT 5;"
```

### **Reset User Preferences (Nuclear Option):**
```sql
-- WARNING: This resets ALL user preferences!
UPDATE "user" SET
  default_language = 'ms',
  default_font_family = 'TikTokSans-Regular',
  default_font_size = 24,
  default_font_color = '#FFFFFF';
```

---

## 📝 What Gets Updated?

### **Before:**
```sql
id | email              | default_language
---+--------------------+-----------------
1  | user@example.com   | th               ❌
2  | admin@example.com  | th               ❌
```

### **After:**
```sql
id | email              | default_language
---+--------------------+-----------------
1  | user@example.com   | ms               ✅
2  | admin@example.com  | ms               ✅
```

---

## 🛡️ Safe Migration

Migration script hanya update users dengan:
- `default_language = 'th'` → Ubah ke `'ms'`
- `default_language IS NULL` → Set ke `'ms'`

**Tidak mempengaruhi:**
- User dengan language lain (en, id, ja, etc.)
- Font preferences
- Completion email settings
- Task history

---

## ⚠️ Important Notes

### **1. Existing Users**
User yang sudah login perlu **logout & login lagi** untuk apply preferences baru.

### **2. Browser Cache**
Clear browser cache atau hard refresh (Ctrl+Shift+R).

### **3. In-Progress Tasks**
Tasks yang sedang diproses tetap pakai setting lama. Upload video baru untuk test setting baru.

---

## 🔄 Alternative: Per-User Update

Jika hanya mau update user tertentu:

```sql
-- Update specific user by email
UPDATE "user"
SET default_language = 'ms'
WHERE email = 'user@example.com';

-- Update specific user by ID
UPDATE "user"
SET default_language = 'ms'
WHERE id = 1;
```

---

## 📊 Monitoring

### **Before Fix:**
```bash
docker-compose logs worker | grep "LANGUAGE MODE"
# Output: "Forcing th language..." ❌
```

### **After Fix:**
```bash
docker-compose logs worker | grep "LANGUAGE MODE"
# Output: "Forcing ms language..." ✅
```

---

## 🎯 Full Fix Checklist

- [ ] Run migration script: `update_language.bat`
- [ ] Verify database: All users have `default_language = 'ms'`
- [ ] Restart services: `docker-compose restart backend worker`
- [ ] Logout & login (browser)
- [ ] Upload test video
- [ ] Check logs for `"ms"` language
- [ ] Verify subtitle/translation in Malay

---

## 🚨 Troubleshooting

### **Issue: Script Permission Denied (Linux/Mac)**
```bash
chmod +x update_language.sh
./update_language.sh
```

### **Issue: Database Not Running**
```bash
docker-compose ps
# If postgres not running:
docker-compose up -d postgres
```

### **Issue: Still Shows 'th' After Update**
```bash
# 1. Clear browser cache
# 2. Logout & login
# 3. Check database again:
docker-compose exec postgres psql -U supoclip -d supoclip -c "SELECT default_language FROM \"user\" WHERE email = 'YOUR_EMAIL';"
```

### **Issue: Update Doesn't Persist**
Cek apakah ada `.env` file yang override database URL atau credentials.

---

## 💡 Why This Happened

### **Timeline:**
```
1. Initial Setup: Database seeded with default_language = "th"
2. Users Created: Inherited "th" from default
3. Code Updated: Backend code changed th → ms
4. Schema Updated: New users get "ms" default
5. Problem: OLD users still have "th" in database
6. Solution: Migrate existing users th → ms ✅
```

---

## 📚 Related Files

- `update_language.bat` - Windows migration script
- `update_language.sh` - Linux/Mac migration script
- `update_language_to_ms.sql` - Raw SQL migration
- `frontend/prisma/schema.prisma` - Database schema (line 37)
- `backend/src/config.py` - Backend language config (line 32)

---

## ✅ Expected Result

After running migration:

**Database:**
```sql
✅ All users: default_language = 'ms'
```

**Logs:**
```
✅ "LANGUAGE MODE ACTIVE: Forcing ms language..."
```

**Output:**
```
✅ Subtitles in Bahasa Melayu
✅ Translations in Bahasa Melayu
```

---

## 🎉 Summary

**Problem:** User database masih punya `default_language = "th"`  
**Solution:** Run `update_language.bat` untuk update database  
**Result:** Semua user pakai Bahasa Melayu 🇲🇾

---

**Migration script siap dijalankan!**

Double-click: `update_language.bat` atau jalankan via terminal.
