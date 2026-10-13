# VYRA — Open beta repository

# VYRA — Public beta status

**Stage:** Open beta. Free to download. Each user supplies their own OpenAI API key and incurs their own API usage charges.

## Distribution

| Item | Location |
|---|---|
| Marketing site | https://aypacharrito.github.io/vyra/ (after GitHub Pages deployment) |
| Windows EXE | https://github.com/aypacharrito/vyra/releases/download/v1.0.0-beta.1/VYRA.exe |
| Complete Windows + Clips ZIP | https://github.com/aypacharrito/vyra/releases/download/v1.0.0-beta.1/VYRA-Windows-Beta.zip |
| Source | https://github.com/aypacharrito/vyra |

**Important:** The downloads are available ONLY after the Windows release workflow succeeds. GitHub Pages is available ONLY after the Pages workflow succeeds. Never announce as live before checking both.

## Current scope

- Portable unsigned Windows EXE; not a Windows installer or auto-updater.
- Local chat interface using the user's own OpenAI account and API key.
- Video clipping worker optionally runs locally with Python + FFmpeg.
- Website is a landing page and interactive UI-only preview, not hosted AI chat.
- YouTube, Instagram and TikTok posting code is not connected or live-tested. Official developer approvals and account connections are still required.
- Autonomous agents, multi-user hosted accounts, Stripe subscriptions and paid entitlements are not implemented.

## Future paid service plan

Keep the installer downloadable if you like, but enforce **paid account access on a hosted backend** using authentication + Stripe subscription webhooks + server-side entitlement checks. Do not trust hidden download URLs, local-only checks, or an embedded shared OpenAI API key. Consider moving the application source to a private repository when commercialization begins and keeping a separate public release/download channel.

## Build & deploy

1. Push source to the `main` branch using an account or GitHub App with Contents write access.
2. Enable GitHub Actions and allow the release workflow to write release assets (`Settings → Actions → General → Workflow permissions → Read and write permissions`, where policy allows).
3. `Settings → Pages → Build and deployment → Source → GitHub Actions`.
4. Under `Actions`, run **Build and publish VYRA Windows beta** and **Deploy VYRA website to GitHub Pages** if initial runs did not start.
5. Verify both release links and live site in a fresh browser before sharing.

## Run the Windows app

Extract the ZIP and launch `VYRA.exe`; the desktop edition uses your own OpenAI key saved securely on Windows. See `BETA_STATUS.md` for scope and limitations.
