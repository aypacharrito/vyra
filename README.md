# VYRA Clips 0.2 — Short-Form Creator Studio

**Priorities: 1. YouTube Shorts · 2. Instagram Reels · 3. TikTok.** A runnable **private, single-user Windows application** that processes your own/licensed long-form video locally, uses the OpenAI API to transcribe spoken words and select highlight candidates, burns in subtitles, lets you review each MP4, and offers **official** OAuth and publishing integrations for the three platforms.

> Not a hosted SaaS service or an authenticated multi-user server. **No accounts have been connected, no API app approvals have been granted, and no live publishing integrations have been validated yet.** Connecting them requires your own Google/Meta/TikTok developer credentials, provider approval where applicable, and your explicit authorization. Publishing may be limited to private visibility for unverified/unaudited applications. No view/revenue results guaranteed.

## Fast Windows setup

1. Unzip to a directory on your own Windows 10/11 PC, for example `C:\VYRA-Clips`. Avoid uploading this folder to public GitHub.
2. Install **Python 3.11+**, selecting **Add Python to PATH**. Then install FFmpeg/FFprobe (PowerShell: `winget install Gyan.FFmpeg`). Reopen terminal after installation. Check `ffmpeg -version`, `ffprobe -version`.
3. Double-click **`run_windows.bat`**. The first run creates `.env` and opens it in Notepad.
4. In `.env`, enter `OPENAI_API_KEY=sk-...` with **your own** OpenAI API key. No quotes. Keep it private. **OpenAI API billing is separate from ChatGPT subscriptions.** If VYRA's API key was already added to Vercel, that does *not* automatically populate this **local** `.env`.
5. Save `.env`; double-click **`run_windows.bat`** again. Open **http://127.0.0.1:8765** and import a video.
6. Preview your clips, download MP4s, and copy AI-generated captions. The video stays on your computer; **audio** is sent for transcription and **transcript excerpts** for editorial ranking. Source video is deleted from the application's work directory after processing. Outputs persist under `output/`.

### Processing cost

Default uses `whisper-1` speech-to-text for word-level captions and `gpt-4o-mini` for clip selection, both billed on your OpenAI API project. At $0.006/minute, transcribing 5 / 20 / 50 source hours is ~$1.80 / $7.20 / $18.00 **plus text-model requests**, excluding hardware, electricity and any storage. Prices can change. The engine does not guarantee a "viral score"; scores are *subjective ranking aids*.

`VYRA_VIDEO_ENCODER=h264_nvenc` in `.env` may use an NVIDIA GPU if your version of FFmpeg supports the encoder; otherwise use the default `libx264`. Do **not** switch to costly image/video generation models to edit an existing video: FFmpeg does the cropping and subtitle rendering for free. Current crop is centered rather than face-tracked; audiovisual/nonverbal viral moments may be missed.

## Connecting the big three

The dashboard contains functional `Connect` buttons. They only become useful **after you create approved developer apps** and enter IDs/secrets in `.env`. The credentials below belong to **VYRA**, not Revive. **Never share your OpenAI key or provider secrets in chat or GitHub.**

### 1. YouTube Shorts — first priority

1. In [Google Cloud Console](https://console.cloud.google.com/), make a project, enable **YouTube Data API v3**, set the OAuth consent screen and any necessary test users.
2. Create **OAuth 2.0 Client ID** credentials for a **Web application**, add authorized redirect URI exactly:
   `http://127.0.0.1:8765/api/oauth/youtube/callback`
3. In VYRA's `.env`, set `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`; restart VYRA.
4. In **Connected accounts**, choose **Connect** on YouTube. Authorize your *own channel* through Google. Tokens are stored encrypted in `.local/`, never exposed in the web UI. Clicking **Publish** on a rendered clip calls official YouTube `videos.insert` with a resumable upload; set visibility **Private** for your first test.
5. A vertical clip up to 3 minutes can qualify as a Short, but YouTube decides classification and may restrict uploads from unverified API projects to private until audit. Do not promise public publishing before verifying your project.

Documentation: https://developers.google.com/youtube/v3/docs/videos/insert and https://support.google.com/youtube/answer/15424877.

### 2. Instagram Reels — second priority

1. Use an Instagram **Creator/Business (Professional)** account. Register a Meta app, enable **Instagram API with Instagram Login**, and request `instagram_business_basic` and `instagram_business_content_publish`. Obtain app permissions/review if required.
2. Meta Business Login commonly requires an **HTTPS redirect**. We included `ig-callback-bridge/`, a tiny optional Vercel HTTPS-to-localhost callback relay for the *single-user local app*. Deploy this subfolder to **your own Vercel project**, with an HTTPS address such as `https://your-vyra-callback.vercel.app/api/instagram-callback` (do not reuse another application's callback).
3. Put this **exact public HTTPS URL** in Meta's approved redirect URI settings and in `.env` as `INSTAGRAM_REDIRECT_URI`. Add `INSTAGRAM_APP_ID` and `INSTAGRAM_APP_SECRET`, then restart VYRA.
4. Instagram must fetch the Reel MP4 from an internet-accessible HTTPS URL. VYRA temporarily uploads it to a **separate private Cloudflare R2 bucket**, then creates a short-lived signed `get_object` URL. Configure `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET` for VYRA, with the ability to upload, read and delete in this bucket. Do not use your REVIVE game-package bucket. Meta's fetching of signed URLs must be validated with a real test.
5. Connect through Instagram in the app and authorize the professional account. A confirmed **Publish** action submits a Reels container, polls for processing, then publishes it when ready. **This is public publishing**; no separate private-draft option in VYRA's UI.

**Important:** The localhost relay is intended only for *the same person's browser and local worker*. Do not use it as the security model for public SaaS/multiple users. Use an authenticated hosted backend for that architecture.

Docs: https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login and https://www.postman.com/meta/instagram/folder/y6xustx/reels-publishing.

### 3. TikTok — third priority

1. Create a [TikTok Developer](https://developers.tiktok.com/) app. Add **Desktop Login Kit** and **Content Posting API**, and request approval for `video.publish`.
2. Register exactly `http://127.0.0.1:8765/api/oauth/tiktok/callback` as the desktop redirect URI. Add `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET` to `.env` and restart.
3. Connect TikTok from VYRA: it opens its official authorization page using a random `state` and PKCE. Publishing reads your creator's **current privacy choices** via TikTok's creator info API and asks you to explicitly confirm that clip's posting metadata and visibility.
4. Direct Post runs only when TikTok authorizes the account and `video.publish` scope. **Unaudited apps are restricted to private account/SELF_ONLY posting**, and may be limited by TikTok rate and creator caps. **No unattended background TikTok posting** is provided in this prototype, because the creator consent UX is part of the platform requirements. No TikTok watermark is applied.

Docs: https://developers.tiktok.com/docs/en/login-kit-desktop and https://developers.tiktok.com/docs/en/content-posting-api-get-started.

## Publishing, approvals, and scheduling

- The app does **not** automatically publish after clipping. Review your clip and choose **Publish**. Pick a provider, title, caption, visibility, and check the explicit copyright/account permission confirmation box.
- For YouTube/Instagram you may choose a future time; VYRA adds an approved item to a **local SQLite publishing queue**, runs it automatically only **while the VYRA process is open**, and shows results. TikTok requires a fresh interactive confirmation instead of scheduled autoposting.
- Scheduled publishing is *best-effort*, not a service-level guarantee. If your computer sleeps, the worker is offline, the platform denies access, or credentials expire, the attempt may fail.
- If a provider call fails after an unknown acceptance state, the queue goes to `needs_review` and **never retries automatically** (to avoid duplicate posts). Verify your social account before another attempt.
- No arbitrary bot logins, scraping of copyrighted media, DRM removal, fake views, engagement spam, or monetization guarantees.
- No automatic creator discovery, nonverbal scene detection, face tracking or revenue dashboards yet.

## Structure

- `clip_engine.py` — transcription, highlight selection, subtitle burning, video rendering
- `server.py` — local FastAPI dashboard, jobs, SQLite queue, review-first publishing
- `social.py` — OAuth flows, account token vault, YouTube/Meta/TikTok publisher adapters
- `static/index.html` — VYRA Clips dashboard, export preview, account connections and queue
- `ig-callback-bridge/` — **optional** HTTPS Instagram OAuth callback forwarding for single-user desktop
- `.env.example` — all supported environment variable *names*, no real values
- `tests/` — code tests, no live provider credentials

## Security and operating limits

VYRA binds to `127.0.0.1:8765` only. **Do not deploy the FastAPI app to the public internet.** OAuth tokens are encrypted using Fernet; the encryption key file is held in your local `.local` directory, so physical/OS-user access is still sensitive. `.env`, `.local`, `output`, and `work` are excluded from Git. Do not copy these to a public repo. The HTTP server is designed for one trusted Windows user and is not multi-tenant. Browser UI includes a per-start CSRF token to protect state-changing local requests. Source files can be large and may be malicious: only import footage from trusted sources and keep FFmpeg updated.

Private URLs may be visible in upload service logs; VYRA keeps API keys/tokens out of normal UI responses. Review outgoing captions for misinformation, copyright and account policy before publishing.

## Tests

`python -m compileall -q .` and `python -m pytest -q tests`. Video render requires FFmpeg compiled with libass. Testing platform posting end-to-end requires real (authorized) accounts, app approvals, media hosting and cannot be simulated here.

## Possible next versions

- **0.3:** face/active-speaker crop, real clip timeline, manual in/out editor, better karaoke subtitles, optical scene scoring
- **0.4:** configurable safe posting schedule and YouTube/Instagram analytic feedback, deduplication
- **0.5:** integrate into VYRA agent backend and allow creator-owned channel publishing with durable cloud worker, hosted auth, audit trail and cancel controls
