# Deployment Guide

Deploy AWT Cloud for free using **Vercel** (frontend) + **Render** (backend) + **Supabase** (auth & database).

---

## Architecture

```
User Browser
  ├── Vercel (Next.js frontend)
  │     └── Supabase Auth (login/signup)
  └── Render (FastAPI backend)
        ├── Supabase (PostgreSQL DB)
        ├── Playwright (headless Chromium)
        └── OpenAI / Claude (AI provider)
```

---

## Prerequisites

- [Supabase](https://supabase.com) account (free tier: 500MB DB)
- [Render](https://render.com) account (free tier: 512MB RAM)
- [Vercel](https://vercel.com) account (free tier: hobby plan)
- AI API key: OpenAI or Anthropic (Ollama cannot run on Render)

---

## Step 1: Supabase Setup

1. Create a new project at [supabase.com](https://supabase.com)
2. Note these values from **Settings > API**:

| Value | Where to Find | Used By |
|-------|---------------|---------|
| Project URL | `https://xxxx.supabase.co` | Frontend + Backend |
| Anon Public Key | Project API Keys section | Frontend |
| JWT Secret | JWT Settings (bottom of page) | Backend |

3. Under **Authentication > Providers**, ensure Email is enabled
4. For development, disable "Confirm email" (enable for production)

See [cloud/README.md](../README.md) for detailed Supabase setup.

---

## Step 2: Deploy Backend on Render

### Option A: One-Click (render.yaml)

1. Push your repo to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com) > **New > Blueprint**
3. Connect your repo — Render reads `render.yaml` automatically
4. Set the secret environment variables (see table below)
5. Click **Apply**

### Option B: Manual Setup

1. Go to **New > Web Service**
2. Connect your GitHub repo
3. Configure:
   - **Name**: `awt-api`
   - **Runtime**: Docker
   - **Dockerfile Path**: `cloud/Dockerfile`
   - **Docker Context**: `.` (project root)
4. Set environment variables (see table below)
5. Set **Health Check Path**: `/health`
6. Click **Create Web Service**

### Backend Environment Variables

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `AWT_DATABASE_URL` | Yes | `postgresql+asyncpg://...` | Supabase PostgreSQL connection string |
| `AWT_SUPABASE_URL` | Yes | `https://xxxx.supabase.co` | Supabase project URL |
| `AWT_SUPABASE_ANON_KEY` | Yes | `eyJhbG...` | Supabase anon public key |
| `AWT_SUPABASE_JWT_SECRET` | Yes | `your-jwt-secret` | JWT signing secret |
| `AWT_AI_PROVIDER` | Yes | `openai` | AI provider: `openai` or `claude` |
| `AWT_AI_API_KEY` | Yes | `sk-...` | AI provider API key |
| `AWT_AI_MODEL` | No | `gpt-4o-mini` | Model override (auto-selects if empty) |
| `AWT_CORS_ORIGINS` | Yes | `https://your-app.vercel.app` | Comma-separated allowed origins |
| `AWT_PLAYWRIGHT_HEADLESS` | No | `true` | Always true for cloud (default) |
| `AWT_MAX_CONCURRENT` | No | `1` | Max concurrent tests (1 for free tier) |
| `AWT_SCREENSHOT_DIR` | No | `screenshots` | Screenshot storage path |
| `AWT_UPLOAD_DIR` | No | `uploads` | Upload storage path |
| `AWT_SENTRY_DSN` | No | `https://...@sentry.io/...` | Sentry error tracking (optional) |

### Database Connection String

From Supabase **Settings > Database > Connection string > URI**:

```
postgresql://postgres.[ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

Change the prefix to `postgresql+asyncpg://` for SQLAlchemy async:

```
postgresql+asyncpg://postgres.[ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

---

## Step 3: Deploy Frontend on Vercel

1. Go to [Vercel Dashboard](https://vercel.com/dashboard) > **Add New > Project**
2. Import your GitHub repo
3. Configure:
   - **Framework Preset**: Next.js
   - **Root Directory**: `cloud/frontend`
4. Set environment variables:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://awt-api.onrender.com` (your Render URL) |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xxxx.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your Supabase anon key |

5. Click **Deploy**

### CORS Configuration

After Vercel deploys, update the Render backend's `AWT_CORS_ORIGINS`:

```
https://your-app.vercel.app,https://your-custom-domain.com
```

---

## Step 4: Verify

1. Visit your Vercel URL — landing page should load
2. Check backend health: `curl https://awt-api.onrender.com/health`
3. Sign up with email/password
4. Create a test with a URL
5. Verify AI generates scenarios and tests execute

---

## Free Tier Limitations

| Service | Limit | Impact |
|---------|-------|--------|
| **Render Free** | 512MB RAM, sleeps after 15min idle | First request after sleep takes 30-60s; max 1 concurrent Playwright test |
| **Vercel Hobby** | 100GB bandwidth/month | Sufficient for development and demos |
| **Supabase Free** | 500MB DB, 2 projects | Plenty for development |

### Render Sleep Behavior

The free tier spins down after 15 minutes of inactivity. The first request after sleep takes 30-60 seconds as the container restarts. This is acceptable for development and demos but not for production use.

### AI Provider Note

**Ollama cannot run on Render** (requires GPU or significant RAM). For cloud deployment:

- Use **OpenAI** (`gpt-4o-mini` is cost-effective) or **Anthropic** (`claude-sonnet`)
- Set `AWT_AI_PROVIDER=openai` and `AWT_AI_API_KEY=sk-...`
- Or run without AI and use manual scenario input

---

## Troubleshooting

### Backend returns 503 "Supabase not configured"

Set all three Supabase variables: `AWT_SUPABASE_URL`, `AWT_SUPABASE_ANON_KEY`, `AWT_SUPABASE_JWT_SECRET`.

### CORS errors in browser console

Update `AWT_CORS_ORIGINS` on Render to include your exact Vercel domain (no trailing slash):

```
AWT_CORS_ORIGINS=https://your-app.vercel.app
```

### Frontend shows "Backend Unreachable" on status page

- Check that `NEXT_PUBLIC_API_URL` points to the correct Render URL
- Verify the backend is awake: `curl https://awt-api.onrender.com/health`
- Render free tier may be sleeping — first request wakes it up

### Playwright crashes with OOM on Render

Reduce `AWT_MAX_CONCURRENT` to `1`. Chromium uses ~200-300MB RAM, leaving limited headroom on the 512MB free tier.

### Database connection errors

- Ensure `AWT_DATABASE_URL` uses `postgresql+asyncpg://` prefix
- Check Supabase connection pooler settings (port 6543 for pooled connections)
- Verify the password doesn't contain special characters that need URL encoding

### WebSocket connection fails

- Render supports WebSocket on free tier
- Ensure the frontend connects to `wss://` (not `ws://`) for HTTPS backends
- The frontend auto-converts `https://` to `wss://` in the API client
