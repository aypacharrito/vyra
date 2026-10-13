# VYRA automation audit — October 13, 2026

Only VYRA was inspected and changed. No unrelated Codex chats or projects were edited. There were no automation.toml files in the accessible Codex automation directory; the automations present in VYRA were the GitHub workflows, update timer, and Clips posting worker.

| Automation | Finding | Change and behavior |
| --- | --- | --- |
| Windows release | Checkout action reference was truncated; hard-coded 1.1 tag; new Go files did not trigger builds; website binaries and manifest were never refreshed | Verified full action commit references; VERSION drives builds; all desktop and worker sources trigger; one build produces setup, portable files and a checksum manifest; website assets are committed together |
| Website publishing | Pages was not enabled; commits made by GitHub's token don't start new push workflows | Release dispatches Pages explicitly; the Pages workflow checks availability and clearly skips optional hosting when disabled. Vercel deploys the website commit |
| Download links | Mutable installer path could change after an old app fetched its checksum | Updates use a versioned installer path; landing-page downloads retain a stable convenience link |
| Desktop update checks | Startup and six-hour checks existed | Preserved; installer download remains explicitly initiated by the user and hash-verified |
| AI tasks | Agents page was a placeholder | Persisted manual, once and interval tasks with results, cancellation and total run limits |
| AI task restart | No runtime existed | Running claims are saved before the API call; interrupted runs pause their task; no silent retries |
| AI task errors | No runtime existed | Tasks pause after error or cancellation; user reviews and resumes; no repeated billing loop |
| Clips scheduled posting | Read-then-write claim could race Publish now; crash left a sending record ambiguous | Conditional atomic claim; interrupted submissions become needs_review; user checks the platform before retrying |
| Local video processing | Two upload requests could pass the busy check | Busy check and reservation now share one lock |
| Installer packaging | Recursively copied directories could include credentials or output media | Build script includes only tracked worker source and explicitly excludes credentials and generated data |

## Operating limits

AI tasks require VYRA to stay open and internet access. They draft text and code or analyze supplied context. They do not execute generated code, browse the web or publish to social services. A missed recurring schedule runs once on reopen, then advances from that time. Maximum 30 saved tasks, 150 retained runs, one active task, at least 60 minutes between recurring runs, and at most 100 runs per task.

Clips schedules run while the video worker is running. Posting stays review-first and requires explicit consent for each destination. TikTok retains its fresh-confirmation restriction. Instagram staging and OAuth approvals remain account setup requirements.

## Verification

Go integration tests cover semantic streaming events, interrupted streams, provider error redaction, transactional connection validation, saved project context/preferences, task persistence, cancellation, concurrency, budgets, crash recovery and corrupted storage. Clips tests cover subtitle safety/timing, OAuth state handling, vault encryption and atomic publishing claims. Browser verification exercises project creation, preferences, task creation/run/results, streaming and caption rendering with a local provider fixture. The fixture validates the wiring without using a real API key or incurring API charges.

The VYRA 1.2 source was pushed to GitHub, CI passed, and the Windows release published real EXE/ZIP assets. The public Vercel website, stable installer download, portable download, and versioned update manifest returned HTTP 200. The downloaded setup checksum matched its manifest. The optional Pages job originally reported that Pages was not enabled; its availability check now avoids treating unused hosting as a failed release.
