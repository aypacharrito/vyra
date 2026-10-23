# VYRA 1.5.9 — Open Beta

VYRA is a Windows AI workspace with a Steam-inspired library, streaming OpenAI conversations, visible voice captions, project context, repeatable AI tasks and an integrated Clips Studio. VYRA owns its Windows window and embeds Microsoft WebView2 Runtime; it does not launch Edge in app mode. The runtime is included on current Windows versions and can also be installed from Microsoft.

## Install and connect

1. Download `VYRA-Setup.exe` from [the VYRA website](https://vyra-five-lac.vercel.app/). Run it to install for your Windows account. Desktop and Start Menu shortcuts are created. The optional portable ZIP is also available.
2. Open **Settings & connections**, enter your own OpenAI API key and save. Saved keys are encrypted with Windows DPAPI for your account. No shared secret is embedded in the website or installer.
3. Use **Test OpenAI connection**. Use **Load my available models** to see your project's catalog, choose a text model and save. Model access and API billing are controlled by your OpenAI project.
4. Open **Intelligence**, type or dictate a message, and watch the reply stream. Use Stop, Copy, Read aloud or Export as needed.

The beta is free to install; OpenAI usage is billed separately to each user's API project. The public website is a landing page and interactive preview. AI requests run through the installed app. The setup executable is unsigned.

## Web research and models

Live web search is enabled by default. The selected OpenAI model can look up current information and returns clickable source citations. Disable it in Settings for conversations using only model knowledge and supplied material. Search has OpenAI API charges. The app no longer drops conversation history after 40 messages, and it supports longer replies. Provider context, output, access and safety rules still apply. VYRA has the knowledge and tools of its selected API model; connecting a key does not automatically add every ChatGPT or Codex tool.

## Voice and captions

**Live dictation** shows microphone text while you speak when your browser's speech recognition service is supported. Your words remain editable before you send. **Record** is a fallback: stop the recording to send its audio to OpenAI for transcription. Recording stops after two minutes.

**Read aloud** displays each spoken sentence, highlighting words when the browser voice emits word-boundary events. Without those events, the sentence stays visible without fabricated word timing. Configure language, voice and automatic read-aloud in Settings. Browser-generated voices are synthetic. Browser dictation may use that browser's online speech service.

## Projects and code

Add a project with goals and notes, then choose **Work with VYRA**. Attach selected text or code files in Intelligence. The chosen project material is sent with your AI request. Personal instructions can describe your preferences. Assistant modes focus on everyday work, code, content, planning or analysis.

Chats, projects, task history and preferences are saved under `%APPDATA%\VYRA`. The workspace is also cached in the app's browser profile. Export workspace backups from Projects. The installer preserves these files. User data and credentials are excluded from installer packaging.

## AI Tasks

Create manual, one-time or recurring tasks from **AI Tasks**. Templates include content ideas, project review, code quality review and material analysis. Each task has instructions, a reference-context snapshot, model, schedule and total run limit.

Tasks run while VYRA is open. One task runs at a time. A missed recurring schedule runs once on reopen, then advances from that time. Results appear in activity and can continue as a conversation. Errors and cancellations pause the schedule. Interrupted calls are recorded for review rather than silently retried. Each task can run at most 100 times; recurring intervals are at least one hour. Review tasks before enabling paid API calls.

Tasks produce text and code and can research current information using OpenAI web search. They do not execute generated code or control the computer. Social publishing is handled separately by Clips Studio with destination consent.

## Clips Studio

Open **VYRA Clips** in the sidebar: upload, captions, exports, accounts and publishing stay inside the desktop window. Account authorization opens the platform’s official sign-in in your default browser; return to VYRA afterward. If needed, **Set up video tools** installs Python dependencies quietly with progress inside VYRA. Python 3.11+ must be installed. VYRA downloads a verified FFmpeg/FFprobe build into its private local tools folder on first opening Clips. Its progress stays in the app. Use Repair video tools if necessary; no global PATH changes are required. Dependencies go into a private `.venv` in the worker folder.

Clips transcribes spoken audio, selects candidate moments and renders vertical videos locally with word-highlighted captions. Timing comes from the actual transcript timestamps. YouTube, Instagram, Facebook and TikTok integrations require your own authorized accounts, developer credentials and applicable platform approvals. Instagram uses temporary private staging storage, configurable in its App settings. TikTok retains fresh confirmation at posting time.

Posted clips are automatically removed from local storage immediately after every queued destination confirms publication. Failed/uncertain uploads, pending destinations and unsent drafts retain their files. Download a copy or queue additional destinations during that window. Publishing history and social posts remain. Cleanup runs while VYRA is open and resumes after restart.

Use **Connected accounts → Set up connection** to privately import your Google Desktop OAuth JSON or save Meta app details. Connect through each platform’s sign-in screen. Facebook requires explicit Page selection. See [social setup](docs/SOCIAL_CONNECTIONS.md).

Publishing claims are atomic and duplicate active posts are rejected. If a process closes during submission, the record needs review; check the destination before retrying. Scheduled posts require the worker to stay running. Account publishing has not been live-tested without the user's credentials.

## Automatic post preparation

Opening Publish now fills in an AI-selected title and concise description for that platform, using the selected clip transcript and metadata. It is an editorial recommendation, not a virality guarantee. Regenerate requests another version; successful suggestions are cached locally, and edits made while generation is running are preserved. Missing AI access keeps the existing text and reports the fallback explicitly.

Choose automatically is the default timing mode for YouTube, Instagram and Facebook. VYRA compares recent account posting times and available age-adjusted engagement when enough comparable records exist. With insufficient results it chooses an explicitly labeled starter test window. These are estimates, not audience-activity reports. You can choose Post now or a manual time; VYRA must remain open to send scheduled posts. TikTok shows the suggestion but requires current manual privacy selection/confirmation when posting.

New YouTube posts must be Public; an account/platform restriction can still change the actual result, which is shown in activity and blocks local auto-cleanup until resolved. TikTok offers only Public when that account/client permits it and requires you to select it; it never silently falls back to private. Previously reviewed queue records are preserved.

Delete on a clip removes its local MP4/subtitles and cancels approved posts and unsent drafts. It also stops an Instagram container still awaiting publication. It does not remove existing social posts or external original footage. In-flight submissions block deletion until they finish; video playback locks retry automatically after playback closes.

In Instagram App settings, Test posting setup checks the account, upload permission and an actual small temporary-file upload/signed URL read. It never publishes a Reel. Your R2 settings must be configured; see the social setup guide.

## Updates and publishing

Intelligence can work with the VYRA workspace, exported clips, post drafts, available account performance and AI tasks. See [Intelligence workspace actions](docs/INTELLIGENCE.md) for examples, current measurements and optional account permissions. Public submissions and changes to published videos use exact review drafts.

VYRA checks its website at startup and every six hours. Installing an update is user initiated. The installer is fetched from a versioned URL and checked against the manifest's SHA-256 hash before it runs.

`VERSION` drives release builds. `scripts/Build-Release.ps1 -PublishWebsite` builds the desktop app and installer, creates a portable archive, computes the setup checksum and updates website downloads and the manifest together. The Windows release workflow publishes the GitHub release, commits generated download files, and dispatches Pages. Vercel should use `website` as its root with the **Other** framework preset. GitHub Pages requires Actions as its deployment source.

Before distributing a new build, verify its actual website downloads and workflow result. Do not mark a release live just because source files were pushed. The pre-upgrade Windows job failed in runner setup before compilation. The checkout action used a truncated reference; this release replaces it and all other action references with verified full commit hashes. Workflow results must still be checked after pushing.

## Development and checks

Run `go test ./...` and `go vet ./...`. Check interface syntax with `node --check web/app.js`. Install worker requirements plus pytest/httpx, then run `python -m pytest clips-worker/tests -q`. The root Python launcher delegates to `clips-worker`, preserving existing root-launcher data. The installer also uses `clips-worker`.

The test-only Go browser fixture (`VYRA_BROWSER_TEST=1`, `TestBrowserFixture`) provides fake OpenAI responses on port 48821. It never ships in release executables. For isolated manual app testing, `VYRA_DATA_DIR`, `VYRA_PORT` and `VYRA_HEADLESS=1` keep data and browser behavior separate from the normal installation.

See [release notes](RELEASE_NOTES.md) and the [automation audit](docs/AUTOMATION_AUDIT.md). Hosted accounts, payment entitlements and a paid multi-user backend remain future work; the beta remains open as requested.


## Source discovery and video links

In Clips, use **Find a source for me** to save a provider/topic pattern. YouTube uses the connected account's read access; Twitch uses separate encrypted developer credentials. Movies searches Internet Archive feature films with public-domain/Creative Commons license metadata. Always check the source and license conditions.

Each scan considers at most 20 sources and keeps five ranked picks, with a six-hour cache and eight scans per UTC day. Enable automatic discovery to refresh while Vyra is open. Scouting uses measured metadata, with no AI calls. Use source → review rights → Import & make clips, or paste a single supported video link. Imports support public YouTube videos, Twitch clips/VODs, and Internet Archive movie items up to two hours / 2 GB, without sign-in/cookies, access-control or DRM bypass. Downloads can be blocked by the source platform; authorized local uploads remain available.

The highlight pattern preselects at most 24 transcript windows across the source, then makes one AI scoring call: hook 25%, payoff 25%, emotion 20%, standalone clarity 20%, editability 10%. Only scores of at least 65 with adequate payoff/clarity are selected. If scoring fails or no moment qualifies, clips are honestly labeled transcript excerpts, without invented scores. This is speech-based editorial selection; it does not analyze video frames or guarantee virality. Transcribing imported audio still uses your OpenAI credit.

Intelligence can read picks and run the saved bounded discovery pattern. It cannot import external footage or publish directly through these tools. Automatic discovery runs only while the app is open. See [Source discovery](docs/SOURCE_DISCOVERY.md).


## Clip Studio 1.5.6

Vyra opens directly in Clips. The sidebar contains only Clips, Projects and AI Tasks, with Settings below. Discover, Intelligence, new-conversation controls and the conversation list are removed from the interface. Existing saved workspace data is retained. Projects hold creative notes; AI Tasks have clip-focused examples and results stay in their activity view.

The studio has four views: Studio, Library, Publishing and Accounts. Link import is next to local uploads, with optional source scouting inside **Find a source for me**. A charcoal/ivory visual system replaces decorative gradients and stars; the original Vyra mark stays.

Scheduling now enforces a 90-minute interval per platform inside the queue transaction, including manual reservations and recent actual upload attempts. Competing requests cannot reserve the same window. When Vyra reopens with overdue posts, it spaces subsequent deliveries from their actual attempt times, instead of rushing all old reservations out together. One provider upload is active at a time across platforms. Other platforms may use the same time window, but file transfers are serialized. A conflicting manual/now request shows the next available time; an automatic-time conflict refreshes the suggestion for fresh review without replacing edited copy. Schedules run only while Vyra is open; failed or uncertain submissions do not retry automatically.

A queued clip immediately leaves the review Library. Its file is retained for pending deliveries/drafts, then deleted on confirmation from every queued destination, with no ten-minute grace period. A failed/uncertain destination restores the clip to review. Cancelling a queued post frees its reservation and returns its clip. Windows file locks are retried during maintenance. Social posts, original external footage and submission history are preserved.
