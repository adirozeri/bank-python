# S3 Presigned-URL Image in the UI (boto3 practice)

A small learning feature: pull a private image from S3 using a **presigned URL** and
display it in the Streamlit UI. Branch: `s3-presigned-image` (off `main`).

## What a presigned URL is

A presigned URL is a time-limited, signed link to a private S3 object. The backend (which
holds AWS credentials) signs it; the **browser** then fetches the object directly from S3
using that link — no credentials ever reach the browser, and the object stays private.

```
Streamlit UI ──HTTP──▶ FastAPI /s3/image-url ──boto3 (sign)──▶ presigned URL
     │                                                              │
     └──────────────── st.image(url) ── browser GETs ─────────────▶ S3 object
```

## Design decisions

- **Presigning lives in the FastAPI backend**, not the UI. This keeps the existing pattern
  where `ui/chat.py` only talks HTTP and never imports boto3 or holds AWS credentials.
- **Bucket/key are hardcoded** in `app/s3.py` for now (it's a practice feature). A
  follow-up could move them to config and let the UI choose the object key.
- **No keys in `.env`.** Credentials resolve through boto3's default chain to
  `~/.aws/credentials` — see "Credentials" below.

## Changes

| File | Change |
|------|--------|
| `app/s3.py` (new) | `generate_image_url()` — builds a boto3 S3 client and returns a presigned GET URL. |
| `app/main.py` | New endpoint `GET /s3/image-url`; wraps the boto3 call in try/except → `HTTPException(502)` so credential/bucket errors surface cleanly. |
| `ui/chat.py` | Sidebar "Load image from S3" button: fetches the URL from the API and renders it with `st.image(url)`. |
| `.env.example` | Removed the `AWS_ACCESS_KEY_ID/SECRET/REGION` lines; replaced with a comment noting creds come from `~/.aws/credentials`. |
| `boto3/` → `boto3_tutorial/` | Renamed the tutorial folder to stop it shadowing the installed `boto3` package (see "Gotchas"). |

### `app/s3.py` (core)

```python
import boto3

BUCKET = "adir-learning-bucket-2026"
IMAGE_KEY = "Screenshot from 2026-06-28 13-32-58.png"
EXPIRES_IN = 3600  # seconds

def generate_image_url(key: str = IMAGE_KEY, expires_in: int = EXPIRES_IN) -> str:
    client = boto3.client("s3")  # creds/region from the default chain
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
```

## Credentials

boto3's default credential chain (same as `boto3_tutorial/boto.ipynb` §2) resolves to:

- **`~/.aws/credentials`** — `[default]` profile (`Method: shared-credentials-file`)
- **`~/.aws/config`** — `region = eu-north-1`

So **nothing goes in `.env`** and there's nothing to set up. On EC2 (Phase 5) the same
code would transparently use the instance's IAM role instead.

> A `.pem` file is **not** an AWS API credential — it's an SSH key for logging into EC2
> hosts. It cannot sign S3 requests, so it plays no part here.

## Gotchas hit during build

1. **`boto3/` folder shadowed the SDK.** The tutorial folder named `boto3/` lived at the
   project root. Because `python run.py` puts the root on `sys.path`, `import boto3`
   resolved to that folder (a namespace package, `boto3.__file__ == None`) instead of the
   installed SDK — so `boto3.client(...)` failed. Fixed by renaming the folder to
   `boto3_tutorial/` (nothing referenced the old path; the notebooks still work).
2. **Use the project venv.** boto3 is installed in `.bank-venv`, not system Python. Run
   with `/home/adir/projects/bank-python/.bank-venv/bin/python` (or activate the venv).

## Verification

Verified end-to-end against the real bucket:

```text
object exists: image/png 49270 bytes
presigned base: https://adir-learning-bucket-2026.s3.amazonaws.com/Screenshot%20...png
fetch via presigned URL: HTTP 200 | 49270 bytes
```

To reproduce:

```bash
cd bank-python-s3
.bank-venv/bin/python run.py             # API on :8000
.bank-venv/bin/streamlit run ui/chat.py  # UI on :8501
curl http://127.0.0.1:8000/s3/image-url  # returns a long signed URL
```

Then click **Load image from S3** in the UI sidebar — the image renders.

## Git note: worktree

This work was done in a **git worktree** (`bank-python-s3/`) off `main`, not a clone, so it
shares one repository with the main checkout while another branch (`mcp`) stays active in
the primary folder. Remove it later with `git worktree remove ../bank-python-s3` — the
branch and its commits survive.
