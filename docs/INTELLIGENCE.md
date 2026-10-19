# Intelligence workspace actions

Intelligence uses OpenAI Responses function calling to perform real operations in the existing local Windows app. Tools are available by default and can be turned off in Settings under workspace access. Requested workspace content and platform measurements are included in the user's direct OpenAI API request; provider tokens, saved keys and private connection settings are never tool results.

Examples:

- “Read my latest exported clip and prepare a better YouTube title and description. Keep it private.”
- “Compare my recent YouTube uploads and Instagram engagement. Show the measurements and suggest three changes.”
- “Change that draft's description to a shorter version and keep its current schedule.”
- “Save my channel strategy in a project called Gabagol.”
- “Create a weekly task that checks my recent performance and drafts three ideas, for four runs.”
- “Show my scheduled posts and cancel the one I named.”

The publishing form's Improve with Intelligence button carries the current clip, destination, draft text, visibility and schedule into the conversation. Actual actions appear beside the reply and are recorded locally. Saved post drafts are also visible in Clips after restarting.

## Available capabilities

The fixed tool registry covers project and conversation reads, project writes, task listing/creation/editing/run/stop/pause/resume, exported clips and their transcripts, local clip metadata, post-draft preparation/revision, publishing activity and pending-post cancellation, measured performance, prepared YouTube metadata edits, voice/search preferences, and navigation inside VYRA. Selected reference files remain available through the existing attachment flow. Background tasks may research, read measurements, prepare drafts and update notes; they cannot create/run other tasks or navigate the desktop.

The interface does not expose arbitrary HTTP requests, shell commands, arbitrary computer files, credentials, permission grants, account deletion, or a final publishing endpoint. Tool inputs are validated against an explicit strict schema. Transcript text, video descriptions, archived conversations and web content are reference data, not authority to perform actions.

## Post review and recovery

Preparing a draft does not publish or schedule it. Each draft has an account, immutable destination, revision and submission state. A human reviews its exact title, description, visibility and schedule, then confirms submission in Clips. Revisions invalidate an older review. A changed connected account blocks submission. A transactional claim prevents duplicate submission; uncertain remote outcomes become review_required and never automatically retry. Existing queue delivery rules still apply. Publishing activity refreshes read-only YouTube processing and actual visibility, preserves the original receipt, and links to Studio. Instagram checks saved sign-in and hosting before queueing; a preflight rejection sends nothing and keeps the draft editable.

Published-video edits currently support YouTube titles and descriptions. The saved edit includes the original text and ETag; approval rechecks ownership and staleness, preserves mutable snippet fields such as tags/category/language, and leaves privacy unchanged. Instagram draft descriptions can be prepared locally; editing existing Instagram posts is not implemented.

## Performance and optional account permissions

YouTube basic counts use the existing youtube.readonly permission. The report samples up to 50 recent channel uploads, includes published dates and durations, and labels counts as lifetime measurements. It does not assume every short upload is classified as a Short, and it does not claim a title caused a result. Missing or hidden counts are null.

Watch-time reports require the optional yt-analytics.readonly scope and YouTube Analytics API enabled in the same Google project. The button in Clips opens Google's incremental authorization screen. Reports include exact dates and returned column names; the newest two days are omitted to allow for reporting delay. If unavailable, the report retains basic counts and explains the missing analytics.

Editing a published YouTube video requires optional youtube.force-ssl permission and an explicit review. The editing button requests incremental access and preserves existing grants. Reconnection verifies the channel again. No broader grant is requested by ordinary Connect account.

Instagram currently returns available recent-media captions, types, dates, links, like counts and comment counts. Reach, watch time, views and retention are not implemented; they are not estimated or presented as measured. Facebook and TikTok performance are not implemented. Existing connections and publishing support remain available.

## Implementation references

- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.google.com/youtube/v3/docs/videos/list
- https://developers.google.com/youtube/v3/docs/videos/update
- https://developers.google.com/youtube/analytics/reference/reports/query

Stateless tool continuations preserve raw response output items, including encrypted reasoning, and append matched function_call_output items. Calls execute sequentially, have a finite turn limit, respect cancellation and are audited without arguments or credentials. No generated code is executed.
