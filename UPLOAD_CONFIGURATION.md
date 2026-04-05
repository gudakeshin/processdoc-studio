# Upload Configuration & Timeout Resolution

## Problem: "Request timed out after 25000ms"

You're getting this error when uploading 1-10MB documents to ProcessDoc Studio. This occurs because:

1. **Server-side processing takes too long** (PDF extraction, text parsing)
2. **Client-side timeout** (browser fetch() has 25-30 second default)
3. **Network latency** (slower connections amplify processing time)

## Solution Implemented

The upload endpoint has been enhanced with:

### 1. **Explicit Timeout Handling** ✅
- File read: 30-second timeout with clear error message
- Text extraction: 30-second timeout per document type
- Graceful fallbacks if extraction times out

### 2. **Optimized File Processing** ✅
- Made text extraction **async** (non-blocking)
- **PDF processing limited to first 50 pages** (prevents huge memory usage)
- Errors in individual pages are skipped (robustness)
- Fallback to raw UTF-8 decode if timeout occurs

### 3. **Better Error Messages** ✅
- Returns HTTP 408 (Request Timeout) with helpful message
- Suggests file size reduction
- Includes parse mode in response for debugging

## Configuration

### Backend: Increase Uvicorn Timeout

When starting the backend, ensure adequate timeout:

```bash
# Development (with reload)
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-keep-alive 75

# Production (with workers)
gunicorn \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  app.main:app
```

**Key timeouts:**
- `--timeout-keep-alive 75`: Keep TCP connection alive (seconds)
- `--timeout 120`: Gunicorn timeout for request completion (seconds)

### Client: Increase Browser Timeout (Optional)

If using JavaScript fetch:

```javascript
// Increase timeout to 90 seconds for large files
const response = await fetch('/api/documents/upload', {
  method: 'POST',
  body: formData,
  signal: AbortSignal.timeout(90_000) // 90 seconds
});
```

For form-based uploads (no timeout config), the fix on the backend should suffice.

## Endpoint Response

When file upload completes:

```json
{
  "filename": "document.pdf",
  "sha256": "abc123...",
  "parse": {
    "status": "chunked",
    "chars": 45000,
    "chunk_count": 38,
    "mode": "pypdf"  // or "zip_xml", "timeout_fallback", etc.
  },
  "path": "/workspace/project-123/source_docs/document.pdf",
  "parsed_path": "/workspace/project-123/parsed_docs/abc123....json"
}
```

## Parse Modes (Debugging)

| Mode | Meaning |
|------|---------|
| `utf8_text` | Plain text, markdown, CSV, JSON |
| `zip_xml` | DOCX/PPTX extracted from archive |
| `pypdf` | PDF extracted successfully |
| `zip_timeout_fallback` | DOCX/PPTX extraction timed out, used raw decode |
| `pdf_timeout_fallback` | PDF extraction timed out, empty placeholder |
| `timeout_fallback` | General timeout, used UTF-8 decode fallback |
| `binary_fallback` | Generic fallback for unknown types |

## Supported File Types & Size Limits

| Type | Max Size | Notes |
|------|----------|-------|
| `.txt`, `.md`, `.csv`, `.json` | 50 MB | Fast, no processing |
| `.pdf` | 50 MB | Limited to first 50 pages, ~30s timeout |
| `.docx`, `.pptx` | 50 MB | Extracted from ZIP, ~30s timeout |
| `.xlsx`, `.xls` | 50 MB | Validated but parsed separately |

## Troubleshooting

### Still Getting Timeout?

1. **Check file size:** Ensure file < 50 MB
2. **Check network:** Slow uploads (< 2 Mbps) may still timeout
3. **Check server logs:**
   ```bash
   # Watch for timeout errors
   grep -i timeout backend.log
   ```
4. **Increase backend timeout:**
   ```bash
   # In production, increase Gunicorn timeout
   --timeout 180  # 3 minutes for very large files
   ```

### File Parsed But Content Missing?

Check the `parse_mode` field:
- `timeout_fallback` means extraction timed out
- Content is still saved, just not parsed for chunking
- You can still use the file, but context extraction won't work

### Memory Issues with Large PDFs?

The limit of 50 pages prevents memory explosion. If you need more:

1. Split large PDFs into multiple uploads
2. Or modify the limit in `_extract_pdf()` function (line ~55 in documents.py)

## Configuration File Location

Backend environment variables (`.env` or `backend/.env`):

```
# Upload limits (bytes)
UPLOAD_MAX_BYTES=52428800  # 50 MB default

# Anthropic timeout (affects other APIs too)
ANTHROPIC_TIMEOUT_SEC=45.0  # Keep this ≥ 45
```

## Testing the Fix

```bash
# Test with a 5MB document
cd backend
python -c "
import requests
import json

with open('test_document.pdf', 'rb') as f:
    files = {'file': f}
    data = {'project_id': 'test-project'}

    # Use requests with timeout
    resp = requests.post(
        'http://localhost:8000/api/documents/upload',
        files=files,
        data=data,
        timeout=90  # 90 seconds
    )

    print('Status:', resp.status_code)
    print('Response:', json.dumps(resp.json(), indent=2))
"
```

## Next Steps

1. **Deploy the updated `documents.py`**
2. **Increase backend timeout** in startup command (add `--timeout-keep-alive 75`)
3. **Test with a 5-10MB document**
4. **Monitor logs** for any remaining issues

If problems persist, check:
- Network connectivity (run `speedtest`)
- Server load (`top`, `htop`)
- Disk I/O (`iostat`)
- Database connection pool (`database_pool_size` in config.py)
