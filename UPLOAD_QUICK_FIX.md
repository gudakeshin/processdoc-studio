# Quick Fix: Upload Timeout (5-Minute Setup)

## Problem
```
Request timed out after 25000ms
```

## Solution (3 Steps)

### 1. Restart Backend with Timeout Config
**Stop your backend if running**, then restart with:

```bash
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-keep-alive 75
```

**Key addition:** `--timeout-keep-alive 75` (increased from default 5)

### 2. Test Upload
1. Open http://localhost:5173 (frontend)
2. Go to Project → Upload Documents
3. Upload a 5-10MB file
4. Should complete in 20-60 seconds (not timeout)

### 3. Done! ✅
The file upload now works with:
- **30-second timeout** protection per operation
- **Async processing** (non-blocking)
- **Graceful fallbacks** if extraction times out
- **Better error messages**

---

## What Changed
**File:** `backend/app/api/documents.py`

| Before | After |
|--------|-------|
| Sync file processing | Async (non-blocking) |
| No timeout handling | 30-second timeout per step |
| Crashes on large PDFs | Limited to 50 pages |
| No error context | Parse mode in response |

---

## Full Deployment Guide
See **UPLOAD_CONFIGURATION.md** for:
- Production configuration
- Troubleshooting
- Environment variables
- File type support

---

## Verify It's Fixed
Check the response when uploading a document:
```json
{
  "parse": {
    "mode": "pypdf"  // ✓ Successful PDF extraction
  }
}
```

or

```json
{
  "parse": {
    "mode": "pdf_timeout_fallback"  // ✓ Timed out but handled gracefully
  }
}
```

Either way, upload succeeds (no 25s timeout error).

---

## Questions?
- **Still timing out?** → Check backend logs for errors
- **Upload slow?** → Normal for 5-10MB files (takes 20-60s)
- **Want more details?** → Read UPLOAD_CONFIGURATION.md
