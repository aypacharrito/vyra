# Discovery pattern v1

Save a provider and topic in Clips → Find your next clip. For Twitch the topic is a game name, not a free-form video search. Movies uses a licensed feature-film collection. YouTube discovery uses the existing YouTube OAuth connection and requires the YouTube Data API to be enabled for that app. Twitch scouting requires a developer Client ID/secret; it does not add Twitch as a posting destination.

## Repeatable source ranking

| Signal | Weight | Meaning |
|---|---:|---|
| Traction | 40 | Log-scaled views per hour of age; Archive uses downloads with unknown age |
| Freshness | 25 | Linear recency within 14 days, if published date is available |
| Engagement | 20 | Available likes and comments relative to views |
| Channel scale | 15 | Views relative to subscriber count, where public |

Missing signals are excluded and remaining weights normalized. Views divided by age is an exposure-adjusted snapshot, not observed growth velocity. Channel scale is not a comparison with previous videos. Scores are editorial rankings, not measured viral probabilities. Limited-metric providers are labeled accordingly; comparing scores across providers is not meaningful. Source metadata never becomes model instructions.

Scans consider at most 20 candidates, keep five, exclude previously imported links, cache six hours, and allow at most eight uncached attempts per UTC day. Automatic scanning is opt-in, runs every six hours while Vyra is open, and never calls the AI. Manual scans show connection errors. Automatic scans fail quietly and can be retried manually. No user cookies or Twitch/YouTube passwords are read.

## Moment selection

Transcript windows fit the chosen duration. A cheap cue-based prefilter chooses up to three separated windows from each of eight timeline regions, capped at 24. One AI request applies hook 25, payoff 25, emotion 20, standalone clarity 20, editability 10. Each component is 0–5; Vyra calculates the weighted score rather than trusting a model's overall number. A score of at least 65 plus payoff/clarity of at least 3 is required. IDs select exact transcript timestamps; invalid IDs/ratings and duplicate/overlapping selections are rejected. No tools or web browsing are supplied to this model. If scoring is unavailable or none qualify, transcript excerpts are offered without a score.

This is a speech-based starting pattern. It can miss visual jokes, silent action, or moments outside the prefilter. It does not inspect frames, guarantee results, or automatically learn causality from engagement.

## Import and cleanup

Review the source and permission/license conditions, then choose Import & make clips. Links are canonicalized to allowed HTTPS video/item hosts; channels, playlists, credentials, custom ports and arbitrary URLs are refused. Import is limited to one active video job, two hours / 2 GB, a 20-minute download timeout, retries, and a free-space check. The downloader runs separately with fixed options, no shell, no browser-cookie loading and no remote script fetching; its JavaScript runtime and solver are installed as app dependencies. The app does not bypass DRM or sign-in walls.

Temporary download files are removed when processing finishes or fails. A failed source can be retried. A successfully imported canonical link is retained for deduplication even when its exported clips are later deleted. Source URL and pattern version are saved in its export manifest. Existing post review, publishing, cleanup, and deletion behavior stays in place.

Scouting consumes provider quota; transcription and the one highlight request consume OpenAI credit after import. App shutdown pauses automatic discovery and queued posting.
