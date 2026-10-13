# Implementation references

VYRA preserves its existing Go desktop and Python worker architecture. These primary sources were checked while extending it; implementations are adapted to VYRA's local routes and storage.

- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses): semantic output deltas, completion and failure events; used by the streamed desktop conversation route.
- [OpenAI recorded-file transcription](https://developers.openai.com/api/docs/guides/speech-to-text): microphone-recording fallback sent as multipart audio; the live dictation button uses browser speech recognition separately.
- [OpenAI GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra): an additional selectable text model; account model access is checked through the user's API project.
- [MDN SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition): feature detection, interim transcripts and microphone errors.
- [MDN speech boundary events](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisUtterance/boundary_event): captions follow real word-boundary callbacks when available; sentence display is retained when timing is unavailable.
- [GitHub Actions checkout](https://github.com/actions/checkout): the original workflow contained a truncated checkout commit reference. Full commit hashes for checkout, Go/Python setup, artifacts and Pages actions were verified against their official repository tags.

No claim is made that extra source lines train or fine-tune the OpenAI model. The improvements are application capabilities, context management, error handling, persistence and verification.
