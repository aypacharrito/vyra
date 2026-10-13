# VYRA 1.2 — Open Beta

VYRA is a Windows AI workspace with a Steam-inspired library, streaming OpenAI conversations, visible voice captions, project context, repeatable AI tasks and a local Clips Studio.

## Install and connect

1. Download `VYRA-Setup.exe` from [the VYRA website](https://vyra-five-lac.vercel.app/). Run it to install for your Windows account. Desktop and Start Menu shortcuts are created. The optional portable ZIP is also available.
2. Open **Settings & connections**, enter your own OpenAI API key and save. Saved keys are encrypted with Windows DPAPI for your account. No shared secret is embedded in the website or installer.
3. Use **Test OpenAI connection**. Use **Load my available models** to see your project's catalog, choose a text model and save. Model access and API billing are controlled by your OpenAI project.
4. Open **Intelligence**, type or dictate a message, and watch the reply stream. Use Stop, Copy, Read aloud or Export as needed.

The beta is free to install; OpenAI usage is billed separately to each user's API project. The public website is a landing page and interactive preview. AI requests run through the installed app. The setup executable is unsigned.

## Voice and captions

**Live dictation** shows microphone text while you speak when your browser's speech recognition service is supported. Your words remain editable before you send. **Record** is a fallback: stop the recording to send its audio to OpenAI for transcription. Recording stops after two minutes.

**Read aloud** displays each spoken sentence, highlighting words when the browser voice emits word-boundary events. Without those events, the sentence stays visible without fabricated word timing. Configure language, voice and automatic read-aloud in Settings. Browser-generated voices are synthetic. Browser dictation may use that browser's online speech service.

## Projects and code

Add a project with goals and notes, then choose **Work with VYRA**. Attach selected text or code files in Intelligence. The chosen project material is sent with your AI request. Personal instructions can describe your preferences. Assistant modes focus on everyday work, code, content, planning or analysis.

Chats, projects, task history and preferences are saved under `%APPDATA%\VYRA`. The workspace is also cached in the app's browser profile. Export workspace backups from Projects. The installer preserves these files. User data and credentials are excluded from installer packaging.

## AI Tasks

Create manual, one-time or recurring tasks from **AI Tasks**. Templates include content ideas, project review, code quality review and material analysis. Each task has instructions, a reference-context snapshot, model, schedule and total run limit.

Tasks run while VYRA is open. One task runs at a time. A missed recurring schedule runs once on reopen, then advances from that time. Results appear in activity and can continue as a conversation. Errors and cancellations pause the schedule. Interrupted calls are recorded for review rather than silently retried. Each task can run at most 100 times; recurring intervals are at least one hour. Review tasks before enabling paid API calls.

Tasks produce text and code. They do not execute generated code, browse websites or control the computer. Social publishing is handled separately by Clips Studio with destination consent.

## Clips Studio

Use **Set up Clips Worker** to open the included setup window. Install Python 3.11+ and FFmpeg/FFprobe once. Python dependencies go into a private `.venv` in the worker folder. Then use **Launch Clips Studio**.

Clips transcribes spoken audio, selects candidate moments and renders vertical videos locally with word-highlighted captions. Timing comes from the actual transcript timestamps. YouTube, Instagram and TikTok integrations require your own authorized accounts, developer credentials and applicable platform approvals. Instagram requires staging storage. TikTok retains fresh confirmation at posting time.

Publishing claims are atomic and duplicate active posts are rejected. If a process closes during submission, the record needs review; check the destination before retrying. Scheduled posts require the worker to stay running. Account publishing has not been live-tested without the user's credentials.

## Updates and publishing

VYRA checks its website at startup and every six hours. Installing an update is user initiated. The installer is fetched from a versioned URL and checked against the manifest's SHA-256 hash before it runs.

`VERSION` drives release builds. `scripts/Build-Release.ps1 -PublishWebsite` builds the desktop app and installer, creates a portable archive, computes the setup checksum and updates website downloads and the manifest together. The Windows release workflow publishes the GitHub release, commits generated download files, and dispatches Pages. Vercel should use `website` as its root with the **Other** framework preset. GitHub Pages requires Actions as its deployment source.

Before distributing a new build, verify its actual website downloads and workflow result. Do not mark a release live just because source files were pushed. The pre-upgrade Windows job failed in runner setup before compilation. The checkout action used a truncated reference; this release replaces it and all other action references with verified full commit hashes. Workflow results must still be checked after pushing.

## Development and checks

Run `go test ./...` and `go vet ./...`. Check interface syntax with `node --check web/app.js`. Install worker requirements plus pytest/httpx, then run `python -m pytest clips-worker/tests -q`. The root Python files remain a compatibility copy; the installer uses `clips-worker`.

The test-only Go browser fixture (`VYRA_BROWSER_TEST=1`, `TestBrowserFixture`) provides fake OpenAI responses on port 48821. It never ships in release executables. For isolated manual app testing, `VYRA_DATA_DIR`, `VYRA_PORT` and `VYRA_HEADLESS=1` keep data and browser behavior separate from the normal installation.

See [release notes](RELEASE_NOTES.md) and the [automation audit](docs/AUTOMATION_AUDIT.md). Hosted accounts, payment entitlements and a paid multi-user backend remain future work; the beta remains open as requested.
