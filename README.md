# Scriptorium

Convert handwritten or printed document images into formatted `.docx` files. Hybrid stack: Next.js 14 (TypeScript) for the UI, Python serverless functions on Vercel for the backend. Document analysis is powered by Google Gemini 2.5 Pro vision (`google-genai`), and `.docx` generation uses `python-docx`.

## Features

- Drop-zone upload for JPG, PNG, and WEBP up to 10MB.
- Server-side vision analysis: titles, sections, bullets, numbered lists, equations, diagrams, layout detection (single / two column).
- Word document output with Georgia body, Courier equations, centered diagrams, red/black section headings, and decimal numbering.
- Hardened public deployment: origin allowlist, per-IP rate limiting (10 req/min default) plus abuse block (>50 req / 10 min → 1-hour ban), strict security headers, sanitized errors, method and content-type guards.
- Zero database, zero auth, zero Redis. All state is in-memory per function instance.

## Tech stack

- **Frontend**: Next.js 14 (App Router) + React 18, TypeScript strict mode, Tailwind CSS
- **Backend**: Python 3.9+ serverless functions (Vercel runtime), `http.server.BaseHTTPRequestHandler`
- **AI**: `google-genai` (Gemini 2.5 Pro vision)
- **DOCX generation**: `python-docx`
- **State**: in-memory per-function (no DB, no Redis)

## Local setup

Prerequisites: Node 18+, Python 3.9+, and the Vercel CLI (`npm install -g vercel`). `vercel dev` is required locally because `npm run dev` only serves the Next.js frontend and will 404 on `/api/*`.

```powershell
npm install
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env and paste your Gemini API key
vercel dev
```

Open the URL `vercel dev` prints (usually http://localhost:3000) — drop an image, analyze, download `.docx`.

Get an API key at https://aistudio.google.com/app/apikey.

### Frontend-only iteration

If you only want to iterate on the UI without running the Python backend, `npm run dev` works fine — the `/api/*` calls will simply fail until you switch to `vercel dev`.

## Environment variables

| Name | Purpose | Default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Required. Google Gemini API key. | none |
| `GEMINI_MODEL` | Optional model override. | `gemini-2.5-pro` |
| `RATE_LIMIT_MAX_REQUESTS` | Per-IP requests per window. | `10` |
| `RATE_LIMIT_WINDOW_MS` | Window size in ms. | `60000` |
| `MAX_IMAGE_SIZE_BYTES` | Hard cap on base64 image size. | `10485760` |
| `ALLOWED_MIME_TYPES` | Comma list of accepted mime types. | `image/jpeg,image/png,image/webp` |
| `NEXT_PUBLIC_RATE_LIMIT_MAX` | Initial "N req remaining" shown in header (client). | `10` |
| `VERCEL_URL` | Set automatically by Vercel. Used for production origin check. | auto |

## Deployment (Vercel)

```powershell
npm install -g vercel
vercel --prod
```

Then, in the Vercel project dashboard, under **Settings → Environment Variables**, set every variable above (except `VERCEL_URL`, which Vercel sets automatically).

## Security notes

- All API routes call `assert_request` (method, content-type, size, origin) and `check_rate_limit` before any processing.
- In production, `Origin` / `Referer` must match `VERCEL_URL`; non-matching requests are rejected with 403.
- Stack traces, model names, and API key fragments are never returned. 500 responses always return `{"error":"An internal error occurred."}`.
- Every API response carries `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, and `Content-Security-Policy` headers.
- Input sanitization strips HTML tags and null bytes on every string field of the request body.
- File names on the `/api/convert` endpoint are sanitized to `[A-Za-z0-9_]`, max 100 chars.

### Pinned framework version

The Next.js frontend is pinned to `14.2.35` (latest 14.x patch) per the spec. A handful of Next.js advisories are only patched in the 15.x line (image optimizer DoS, request smuggling in rewrites, Server Components DoS, `next/image` disk cache growth). None of these affect this project — the Next.js app ships zero rewrites, no server components, and no `next/image` usage; all dynamic endpoints are Python serverless functions that bypass the Next.js request pipeline entirely.

## Project layout

```
app/
  layout.tsx              root layout + fonts
  page.tsx                single-page client UI
  globals.css             tailwind + palette
api/
  analyze.py              POST: image -> AnalysisResult (Gemini)
  convert.py              POST: AnalysisResult -> .docx bytes
  _lib/
    guardrails.py         method/content-type/origin/size + security headers + sanitization
    rate_limiter.py       per-IP window + abuse limiter (in-memory, thread-safe)
    image_validator.py    data URL parse + mime / size / base64 sanitization
    gemini_client.py      google-genai call + prompt + JSON parse + shape coercion
    docx_builder.py       AnalysisResult -> bytes via python-docx
requirements.txt          Python deps: google-genai, python-docx
```

## Scripts

```powershell
vercel dev       # full-stack local dev (Next.js + Python /api)
npm run dev      # frontend-only dev (no Python API)
npm run build    # production build for frontend (type-checks)
npm run start    # run the built frontend
npm run lint     # eslint
```

## Troubleshooting

- **`404 models/... is not found for API version v1beta`** — the model name in `GEMINI_MODEL` is wrong or not available to your API key. Use `gemini-2.5-pro` or `gemini-2.5-flash` (both publicly available in AI Studio). Preview model names like `gemini-2.5-pro-preview-05-06` are gated.
- **`GEMINI_API_KEY is not configured`** — ensure `.env` exists locally and the Vercel project has `GEMINI_API_KEY` set under **Settings → Environment Variables**.
- **Local `/api/*` returns 404** — you're running `npm run dev` instead of `vercel dev`. The Python functions are only served by `vercel dev` or a deployed Vercel environment.
