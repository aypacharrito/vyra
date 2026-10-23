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
