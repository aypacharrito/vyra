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
