# VYRA 1.5.11

- Reworked the in-app package setup. A healthy private interpreter is reused even if global Python is unavailable. Broken, 32-bit and unsupported interpreters are skipped while checking installed 64-bit Python 3.11–3.13 launcher options.
- Backs up an incompatible private environment before replacement, repairs/upgrades its private pip, installs binary packages and verifies the same imports/timezone/Deno checks used at launch before reporting success. Customer clips, credentials and queues are outside the environment and retained.
- Captures bounded setup output and displays the actual failing step/package under Setup details. Credentials and URLs are redacted. Removed the duplicate failure toast.
- Removed the blue focus outline on the custom Windows buttons and aligned header status/actions with the concept's headline.

Validation: portable interpreter-selection, failure-diagnostic redaction/bounding, asset routing and worker command/listener tests passed. Windows x64 Python 3.11 dependency resolution succeeded with binary wheels. Browser tests covered setup failure details, retry, header/window controls, existing studio/publishing flows and desktop/laptop sizing. Windows-targeted vet, application build and test-binary compilation passed. Actual dependency installation on the user's laptop is unverified; a screenshot of the old generic error does not establish the failing package.

# VYRA 1.5.10

- Replaced PowerShell/WMI/Get-NetTCPConnection worker replacement with direct Windows listener/process APIs. Verifies the legacy VYRA status, exact loopback listener, held process handle, Windows session and Python/uvicorn arguments before replacing it. Both the desktop launcher and shipped batch launcher are recognized; unrelated processes and active uploads stay running. Failures now identify the check that blocked recovery.
- Added Windows integration tests with disposable local worker processes for idle desktop/batch recovery, active-upload protection and rejection of an unrelated command. The normal Windows release test gate executes these before publishing. Portable regression tests cover listener decoding and command validation.
- Removed the standard Windows caption strip. A captionless window retains its native resize frame and has small minimize, maximize/restore and close buttons plus a draggable top strip. Window commands pass through the local authenticated API and execute on the UI thread.
- Fixed the delegated navigation handler matching body[data-view] when clicking ordinary content or window controls, causing unintended studio relaunch attempts. Only navigation buttons now select a view.
- Removed the extra VYRA / CLIP STUDIO overline above the studio headline so the top follows the original concept. Retains the 1.5.9 startup design, 1.5.8 posting fixes and all prior clip features.

# VYRA 1.5.9

- Fixed Windows refusing to replace worker 0.6.5 during the upgrade to 0.6.6. The launcher and replacement script now share one supported legacy-version list, with a regression check for the previous release.
- A verified previous worker is replaced only after the existing publishing check. Active uploads receive a specific wait message; other restart failures no longer incorrectly claim that publishing is active. The replacement waits for its local port to release before the new worker starts.
- Removed the duplicate top repair/reload toolbar. Loading and recovery use the same editorial headline and studio view strip as the design concept, with one recovery message and inline retry/tools controls. Removed the extra WORKSPACE sidebar label to align the navigation with the concept.
- Retains the 1.5.8 publishing conflict fix, exact automatic timestamps and 1.5.7 stylesheet routing fix. Worker protocol stays 0.6.6.

# VYRA 1.5.8

- Fixed the publishing dialog treating all HTTP 409 responses as occupied posting times. Already queued/submitted clips now show the actual duplicate warning instead of repeatedly refreshing the time and asking for confirmation.
- Added explicit conflict identifiers to distinguish duplicate posts from platform spacing conflicts. Only a real time conflict refreshes the suggestion; edited titles/captions remain intact and the new time requires review.
- Submit automatic schedules using the exact suggested timestamp, preserving seconds and timezone offsets instead of passing through the minute-only local input.
- Worker protocol 0.6.6 refreshes old running workers. Includes the 1.5.7 stylesheet route correction and the complete Clip Studio redesign.

# VYRA 1.5.7

- Fixed the installed desktop shell returning 404 for `/studio.css`. The 1.5.6 package contained the redesign stylesheet, but the Go server did not expose its URL, so the old shell styling remained. The new explicit route serves its embedded CSS with the correct MIME type.
- Added a regression test that reads the actual entry HTML and requests every referenced local asset through the real app router, checking exact embedded bytes and stylesheet MIME. The test reproduces the 1.5.6 failure and passes after this fix.
- The Clips worker, scheduling, cleanup and existing three-section redesign are unchanged.

# VYRA 1.5.6

- Redesigned the app around Clips, Projects and AI Tasks. Removed Discover/Intelligence navigation, conversation controls and general-assistant entry points. Opens directly in Clips; saved workspace data remains available in backups.
- Added a charcoal/ivory studio with clear Studio, Library, Publishing and Accounts views. Source links stay prominent, optional scouting is collapsed, and account/publishing controls follow the same visual system.
- Enforced 90-minute posting intervals per platform for manual/automatic queue reservations. Persistent delivery slots prevent overdue queues from posting in a burst after restart. Global upload claims keep one file transfer active at a time.
- Queued clips leave the review Library immediately. Delivery files clear as soon as all queued destinations confirm success, with no ten-minute delay. Pending destinations/drafts retain files; failures and cancellations return clips to review. Windows locks retry safely.
- Time-refresh errors retain manual copy; automatic-time conflicts fetch a fresh suggestion for review. Removed silent switch to Post now when automatic preparation fails.
- Worker protocol 0.6.5 safely refreshes older workers. Windows title, shortcuts and resource descriptions now say Clip Studio.

Validation: 131 worker tests passed, one Windows-only skip; four OAuth tests passed. Browser tests exercised default Clips, all three sidebar sections, studio tabs, task editor, settings, source import, automatic copy/time, Public scheduling, queued-clip removal and Delete. No horizontal overflow at desktop/laptop widths. Windows-targeted app/installer vet and test-binary compilation passed; the app compiled. Windows binaries and real social posting were not executed here.

# VYRA 1.5.5

- Added Discover with a saved provider/topic pattern, optional six-hour automatic refresh, deduplication, metadata-only scouting, and fixed daily/provider budgets.
- Added public video-link import directly into the existing transcription, captioning and clipping workflow: YouTube, Twitch clips/VODs, Internet Archive movies. Requires authorized footage; no private/DRM bypass.
- Added encrypted Twitch discovery credentials and Intelligence tools for reading/scouting picks. YouTube reuses its existing read connection.
- Replaced unbounded per-transcript-batch highlight requests with a fixed 24-window prefilter and one weighted rubric call. Selection includes timeline diversity, grounded timestamps, minimum payoff/clarity, overlap prevention, and honest fallback labels.
- Includes all 1.5.4 AI post copy/time, public posting, clip deletion, storage cleanup and Instagram publishing repairs. Worker protocol 0.6.4 refreshes old workers; setup installs the downloader and bundled JavaScript runtime.

Validation: 121 worker tests passed, one Windows-only test skipped on Linux; four OAuth callback tests passed. UI flow covers discovery settings/picks/import and the existing publishing flow. Windows-targeted vet, application build and test-binary compilation passed. Live provider downloads, account discovery, and social posting still need verification with connected accounts in the installed app.

# VYRA 1.5.4

- Bump the worker protocol to 0.6.3 so old running 0.6.2 workers are detected and replaced safely instead of silently reused.

- Generate three grounded, platform-specific title/description candidates, select one editorially and fill the review form automatically. Reuse saved copy to avoid paying again on every reopen; Regenerate requests a fresh version. Preserve text typed while AI is working.
- Choose a future posting window in the device timezone. Use recent account posting-time/engagement associations when enough comparable results exist; otherwise identify it as a starter experiment. Avoid nearby queued posts. Keep the suggested time visible and allow Post now/manual overrides. No reach or virality guarantee.
- New YouTube posts are Public only. Instagram/Facebook publish Reels. TikTok requires an explicit Public selection at posting time; do not silently send private copies or schedule past its fresh-confirmation requirement. Existing reviewed queue records are not rewritten.
- Add Delete on each clip. Cancel approved posts and unsent drafts, stop pending Instagram containers from publishing, remove local MP4/subtitles, and retry Windows playback locks. Existing social posts and external source files remain.
- Test Instagram sign-in plus an actual temporary-storage upload and signed GET, with no social publication. Use explicit S3v4 signing and safe stage-specific failure messages/codes. Distinguish format rejection from failed media downloads.
- Keep local files when YouTube reports a visibility different from the requested Public setting.
- Repair the TikTok upload receipt's account reference and disable interactions unless separately implemented/authorized.

# VYRA 1.5.3

- Auto-delete local MP4s and generated subtitle files ten minutes after all queued destinations confirm posting. Keep receipts, pending/uncertain posts, unsent drafts and original user footage.
- Verify YouTube processing, Instagram publication, Facebook published/ready status and TikTok PUBLISH_COMPLETE before allowing cleanup. Recheck in the background while VYRA runs; retry locked Windows files after playback closes.
- Keep Instagram processing containers and temporary files across restarts. Poll instead of timing out after two minutes, and publish each approved container once. Unknown write outcomes stop for review.
- Add private R2 storage setup to Instagram App settings, detect missing publishing permission, avoid refreshing fresh tokens too early, and explain which Instagram app credentials to use.
- Route the source launcher through the same worker shipped in the desktop app.

Install this release through the verified Windows release workflow. Source changes alone do not update an already-installed copy. No live account post or Windows installation was performed during this change.

# VYRA 1.5.2 Open Beta

- New YouTube posts default to Public in the publishing form, Intelligence drafts and the upload request. Explicit visibility choices remain available for individual posts, and activity checks the actual privacy YouTube applied.
- Instagram reconnection supports Meta's current wrapped authorization response as well as the earlier response format. Incomplete responses preserve the saved connection and credentials remain encrypted.
- The desktop and Intelligence use the same Studio version check when replacing an older idle worker.

# VYRA 1.5.1 Open Beta

- Publishing activity checks the actual YouTube upload, processing and visibility result, shows when it was checked, and links directly to the video and YouTube Studio. Refreshing status never uploads again or changes privacy.
- Private and unlisted uploads explain why they do not appear publicly on the channel. Requested visibility stays distinct from the platform's actual result. Invalid or missing upload receipts require review.
- Instagram checks saved sign-in and video hosting before publishing. Rejected connections and missing setup appear on the account card and block submission. A rejected preflight preserves an editable draft and reports that no post was sent.
- Intelligence reads the same verified publishing results. Existing submissions, encrypted connections, clips and drafts are preserved.

# VYRA 1.5.0 Open Beta

- Intelligence can operate VYRA through typed workspace actions: inspect clips and transcripts, save local clip text, prepare and revise post drafts, read publishing activity, cancel pending scheduled posts, manage project notes and AI tasks, and adjust voice/search preferences.
- Real recent-upload performance from the connected YouTube channel and available Instagram engagement. Lifetime counts and optional time-windowed YouTube Analytics reports are kept distinct; missing measurements remain unknown.
- Durable post drafts with account binding, revision checks, exact human review and duplicate submission protection. A conversation can fill the review form directly. Published YouTube title/description edits preserve unrelated metadata and require separate editing permission plus review.
- Use Intelligence from the clip publishing form, keep the current clip selection in conversation context, and see actual actions beside the answer. Background AI tasks can use the same workspace tools without spawning other tasks or submitting posts.
- Workspace access can be disabled in Settings. Account secrets stay inside their existing encrypted connectors. Optional Google analytics/editing authorization is requested through explicit buttons; existing publishing scopes are not silently expanded.
- Background project updates survive saves from older open windows. Explicit deletions are tracked so a stale window cannot restore deleted projects.
- Connected accounts have a Reconnect button. Expired Instagram access produces a specific renewal message without exposing provider tokens or private error text.

# VYRA 1.4.2 Open Beta

- Install the verified FFmpeg/FFprobe engine privately when Clips first opens. Download progress stays inside VYRA, and no terminal or global PATH editing is needed.
- Resolve private engine paths directly for probing, audio extraction, rendering and captions. A Repair video tools button is available inside Clips.
- Check video-engine readiness before accepting an upload, and retain uploaded source files after processing errors.
- Video-engine archives are pinned, checked against the publisher’s SHA-256, extracted to a staging folder and validated for caption support before activation.
- Replace a verified older Clips worker when opening the updated studio, after checking that no publishing submission is active.
- When highlight selection returns no usable timings, prepare real transcript excerpts for review. These are labeled as transcript excerpts and do not receive an invented AI score.

# VYRA 1.4.1 Open Beta

- Accept complete OpenAI secret keys pasted with quotes, a Bearer label, environment-variable wrappers or invisible formatting characters. Remove the obsolete 500-character key limit in both the app and its video worker.
- Explain when a shortened key, key name or ID is pasted. Connection errors stay visible below the private key field and never include the secret.
- Save & test checks the newly saved key automatically. The separate Test button saves a newly entered key first, rather than testing an older saved key.

# VYRA 1.4 Open Beta

- A native Windows window with the VYRA icon, powered by the embedded WebView2 Runtime. Opening VYRA no longer launches Microsoft Edge in app mode.
- Clips Studio inside the desktop app: creation, captions, connected accounts, exports and publishing. Switching workspace sections preserves the open studio and selected inputs. Platform sign-in opens in the default browser and returns to the existing local connection flow.
- Live OpenAI web search in conversations and AI tasks, with clickable citations and source titles. Research requests return findings and links. Search can be disabled in Settings.
- Complete conversation history is sent within the provider context window, with longer messages, reference material and answer output. Interrupted answers remain visible.
- Quiet video dependency setup with progress inside VYRA, plus hidden FFmpeg windows. A desktop-owned worker picks up a newly saved OpenAI key for subsequent work.
- Existing encrypted keys, social connections, conversations, projects and tasks survive the update.

OpenAI model capabilities, access, context limits, service rules and API billing still apply. VYRA does not automatically inherit every ChatGPT or Codex tool. Instagram publishing still requires private temporary media hosting. Facebook remains optional.

# VYRA 1.3 Open Beta

- The same VYRA hexagon/V symbol, refined with metallic highlights and subtle depth across desktop, setup, website and Clips Studio.
- Guided connection setup inside Clips Studio. Import a Google Desktop OAuth client JSON file or privately save Meta app details; no manual `.env` editing is required for these connections.
- Facebook Page sign-in, explicit Page selection and Facebook Reels publishing with the official local-upload flow. Uploads require reviewing and confirming the selected destination.
- Google sign-in uses PKCE and verifies the selected YouTube channel. Account tokens and app credentials use a Windows-account-protected encryption key.
- HTTPS callback relays for Instagram and Facebook, one-use OAuth state checks, hidden credential fields, safe callback errors and disabled worker access logs.

Social connections still require the user's developer app, granted permissions and any platform approval. Instagram publishing also needs temporary media hosting configured separately. No account is reported as connected until authorization completes; Facebook also requires selecting a Page. No social posts are made during setup.

Includes the VYRA 1.2.1 setup improvements:

- A native, branded Windows setup window with installation progress, accessible buttons, retry after failure and automatic reopening after an update.
- Silent PowerShell and registry helpers during installation and removal, so setup no longer flashes command windows.
- Multi-size VYRA icons embedded in the desktop app and installer, used by Windows shortcuts and the desktop window's favicon. Windows file properties now show the product name and release version.
- OpenAI connection status refreshes when a VYRA window regains focus and while it is visible. Saving or testing a connection in one window updates the other windows without restarting.

Includes the VYRA 1.2 features:

- Streaming OpenAI replies with Stop, visible partial answers, readable code, Copy and Export.
- Live microphone dictation with on-screen text when the browser supports it, plus recorded-audio transcription through OpenAI.
- Read-aloud replies with sentence captions and word highlighting when the selected browser voice supplies word boundaries.
- Project notes and selected text/code attachments used as reference context. Everyday, coding, creator, planning and analysis modes.
- Personal instructions, voice preferences and model selection, including loading models available to the user's API project.
- Local AI tasks: manual, one-time and recurring schedules; one task at a time; run limits; cancellation; persisted results; restart recovery; pause after errors.
- Word-highlighted Clips subtitles using transcription timestamps, atomic publishing claims, and review of interrupted uploads.
- Versioned installer downloads, SHA-256 update verification and a release pipeline that updates website assets and the update manifest together.

The beta is free to install. OpenAI usage is billed to each user's API project. AI tasks run while VYRA is open. Live dictation depends on browser support. Social posting requires the user's authorized accounts and the platform's required approvals. No arbitrary computer-control or shell execution is included. The installer is unsigned.
