# GenHealth Order Intake API

A Python REST API for durable medical equipment (DME) order intake. Upload a faxed or scanned order
PDF and the service extracts the **patient's first name, last name and date of birth** and the
**ordering provider's name and NPI**, validates every value in code before saving, and never guesses
a missing field. Orders support full CRUD and are private to the user who created them.

**Live:** https://genhealth-orders.onrender.com &nbsp;·&nbsp; **Interactive docs:**
https://genhealth-orders.onrender.com/docs

> Hosted on Render's free tier: the first request after ~15 idle minutes can take 30–60 s while the
> service wakes up.

## Try it

**In the browser:** open [/docs](https://genhealth-orders.onrender.com/docs), call
`POST /auth/register`, click **Authorize** (email as username), then `POST /orders/upload` with a
PDF.

**With curl:**

```bash
BASE=https://genhealth-orders.onrender.com

curl -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password"}'

TOKEN=$(curl -s -X POST $BASE/auth/login \
  -d 'username=you@example.com&password=a-strong-password' | jq -r .access_token)

# Create an order from a PDF
curl -X POST $BASE/orders/upload -H "Authorization: Bearer $TOKEN" -F 'file=@order.pdf'

# List, read, fix, delete
curl "$BASE/orders?status=needs_review" -H "Authorization: Bearer $TOKEN"
curl -X PATCH $BASE/orders/<id> -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"provider_npi":"1234567893"}'
curl -X DELETE $BASE/orders/<id> -H "Authorization: Bearer $TOKEN"
```

Uploading the provided sample fax returns (abridged):

```json
{
  "status": "needs_review",
  "patient_first_name": "Marie", "patient_last_name": "Curie", "patient_dob": "1900-12-05",
  "provider_name": "Arjun Raj", "provider_npi": null,
  "validation_issues": [
    {"field": "patient_dob", "code": "implausible", "severity": "warning",
     "message": "Implausible age (125 years); verify date of birth"},
    {"field": "provider_npi", "code": "invalid", "severity": "error",
     "message": "NPI fails the CMS check-digit (Luhn) validation", "rejected_value": "9182734556"}
  ],
  "extraction": {"model": "gpt-5.5", "page_count": 4, "skipped_blank_pages": [4], "fields": {"...": "value, page, quoted evidence, confidence"}}
}
```

The sample is full of traps, and each is handled: it is image-only (no text layer); it names two
physicians, and the **prescriber** (Arjun Raj) is chosen over the **referring** physician (Gregory
House); the printed NPI fails the official check digit, so it is **rejected rather than saved**; the
DOB is real but implies age 125, so it is kept and flagged; and the trailing blank page is skipped.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Create an account (email, password ≥ 8 chars) |
| `POST` | `/auth/login` | OAuth2 password form → JWT bearer token (60 min) |
| `GET` | `/auth/me` | Current user |
| `POST` | `/orders/upload` | Create an order from a PDF (multipart `file`) |
| `POST` | `/orders` | Create an order manually |
| `GET` | `/orders` | List own orders: `limit`, `offset`, `status=needs_review\|ready` |
| `GET` | `/orders/{id}` | Read one order |
| `PATCH` | `/orders/{id}` | Partial update; editing a field resolves its issues |
| `DELETE` | `/orders/{id}` | Delete |
| `GET` | `/health` | Liveness + database check |

Every order query is filtered by owner; another user's order returns **404** (not 403) so IDs are
not disclosed. IDs are UUIDs.

## How extraction works

```
PDF ─► checks ─► render pages ─► vision LLM ─► code validation ─► NPPES check ─► Order
       size,     blank-page      one call,      null + issue       registry
       type,     skip, auto-     strict JSON    on any failure     name match
       encrypted rotate          schema
```

1. **Upload checks** (`app/api/orders.py`, `app/extraction/pdf.py`): max 20 MB, `%PDF` magic
   bytes, corrupt / password-protected / blank-only files rejected with a clear 4xx *before* any
   model cost. Up to 30 non-blank pages are processed.
2. **Page preparation** (`pdf.py`): each page is rendered to an image (150 DPI). Blank pages are
   skipped. Pages scanned sideways are detected without OCR (row vs. column ink-profile contrast)
   and rendered upright, because the eval showed the model misreads sideways text. Any embedded
   text layer is sent alongside the image.
3. **One vision-model call** (`llm.py`, OpenAI Responses API, `gpt-5.5`): structured output against
   a strict schema (`schema.py`). Each field returns `value | null`, `source_page`, verbatim
   `evidence`, `confidence`, and `conflicting_values`. The prompt defines the ordering provider
   (the prescriber who signs, not the referring physician, supplier, or note author), forbids
   inferring or "correcting" values, and requires the NPI digits exactly as printed.
4. **Code decides what is saved** (`service.py`, `app/validation.py`). The model only proposes.
   - *Rejected (saved as null, issue with `rejected_value`)*: missing; NPI not 10 digits or failing
     the CMS Luhn check digit; DOB not a real date, in the future, or before 1900; names with digits
     or symbols.
   - *Kept but flagged (warning)*: implausible age (>120), low model confidence, conflicting values
     in the document, quoted evidence not found on the cited page (when a text layer exists), NPI or
     name absent from its own evidence, multiple patients, NPI not in NPPES, NPPES name mismatch, or
     an organization NPI.
5. **NPPES cross-check** (`nppes.py`): the public CMS registry is queried with a 5 s timeout; an
   outage is recorded and never blocks the upload.
6. **Status**: `ready` only when all five fields are present and no issues remain; otherwise
   `needs_review`. A `PATCH` to a field is treated as human review and clears that field's issues.
   If the model call itself fails, the order is still created (all fields null,
   `extraction_failed`) so the document is not lost and can be completed manually.

Adding a field (e.g. HCPCS code) means adding it to `ExtractionResult` in `schema.py`, the
`Order` model + a migration, and a validator.

## Accuracy evaluation

`scripts/make_eval_pdfs.py` generates labelled synthetic orders that target real failure modes;
`scripts/eval.py` runs the full pipeline and scores the values that would be **saved**, separating
*wrong saved* (dangerous: a bad claim) from *missed* (safe: a human fills it in).

| Case | Trap |
|---|---|
| `clean_typed` | Baseline digital PDF |
| `last_first_scanned` | `HERNANDEZ, LUIS A.`, `3-14-1962`, speckled 110 DPI scan |
| `referring_trap_scanned` | Referring physician + NPI listed before the ordering physician |
| `missing_dob_and_npi` | No DOB/NPI, but order and service dates present (must stay null) |
| `multipage_buried` | 6 pages: supplier NPI on cover, subscriber DOB on insurance page, blank pages, order on p.5 |
| `rotated_skewed_lowres` | Sideways, 2.5° skew, 90 DPI, heavy speckle |
| `sample_cpap_fax` | The provided sample (invalid NPI must not be saved) |

```
$ uv run python scripts/eval.py
Overall: 35/35 correct (100%), 0 wrong saved, 0 missed      (gpt-5.5, ~4–10 s per document)
```

The first run scored 34/35 and surfaced two real bugs, both fixed and covered by tests: sparse
scanned pages were being classified as blank (the order would have been dropped), and a sideways
scan produced a confidently wrong first name ("Owein" for "Owen") until auto-rotation was added.
gpt-4.1 and gpt-5.4 also extract the sample correctly; gpt-5.5 was fastest. Seven documents is a
smoke-level eval, not a statistically meaningful benchmark; see next steps.

## Security and production notes

- Passwords hashed with argon2; login timing is uniform for unknown emails; JWT secret is required
  in production (the app refuses to start with the default).
- Rate limits: registration 5/min and login 10/min per IP, uploads 10/min per user (each upload
  costs a model call). In-process; a multi-instance deployment would back this with Redis.
- Logs are structured JSON with a request ID (`X-Request-ID`), and record paths, status codes and
  issue codes only: no request bodies, document text, or extracted values (PHI).
- Uploaded PDFs are not stored; the order keeps the filename and SHA-256 for traceability.
- Migrations run on container start with retries, so a cold database does not crash the deploy.

## Local development

```bash
uv sync
cp .env.example .env            # set OPENAI_API_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload        # http://localhost:8000/docs

uv run pytest                               # 69 tests, no network or API key needed
uv run ruff check . && uv run ruff format --check .
uv run python scripts/eval.py               # accuracy eval (calls OpenAI)
uv run python scripts/extract_pdf.py some.pdf               # debug one document
uv run python scripts/smoke_test.py $BASE tests/fixtures/sample_cpap_fax.pdf   # end-to-end check of a deployment
```

Stack: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (SQLite for local dev and tests), PyMuPDF, OpenAI,
uv, Docker. CI (GitHub Actions) runs lint, format check and tests.

**Deployment:** `render.yaml` is a Render Blueprint that provisions the Docker web service and a
managed Postgres database, and generates `JWT_SECRET`. Only `OPENAI_API_KEY` must be set manually.

## Tradeoffs and next steps

- **Synchronous extraction** (~5–10 s per request) keeps the MVP simple. At volume: accept the
  upload, return `202` with a `processing` status, and extract in a worker queue, with webhooks or
  polling.
- **Store source documents** in encrypted object storage (S3 + KMS) so reviewers can see the page
  next to each extracted value, using the `source_page` + `evidence` already captured.
- **Bigger, real eval set**: de-identified production faxes with double-keyed labels, run in CI
  on prompt or model changes, tracking wrong-saved rate as the primary metric.
- **Second-opinion extraction** on low-confidence or conflicting fields (a different model or a
  higher-resolution crop) before asking a human.
- **HIPAA posture**: a BAA with the LLM vendor and zero data retention, audit logging of PHI
  access, refresh tokens and revocation, and per-organization tenancy instead of per-user.
- **Despeckling and deskewing** for very poor scans; orientation currently handles 90° only.

## How this was built

Built with an AI coding agent (Cursor) as a pair: I set direction, reviewed each step and made the
calls; the agent scaffolded, implemented, tested, and ran the evals. The exported agent sessions
are in [`agent-sessions/`](agent-sessions/).
