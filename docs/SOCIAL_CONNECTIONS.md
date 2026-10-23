# Connect your publishing accounts

Open VYRA Clips → Connected accounts → Set up connection. Save app details
privately in that screen, then choose Connect account. Authorize only the
account or channel you intend to use. The public preview website does not
store credentials or connect accounts for you.

## YouTube Shorts

Enable YouTube Data API v3 in your Google project. Create an OAuth client with
the Desktop app type and download its JSON. Import that file in VYRA's setup
screen. Connect and choose the Google or Brand account for your channel.
VYRA asks for upload and read access to verify and display the channel name.
Testing-mode apps need the user in Google's test-user list. Google may require
verification for broader use; unverified upload projects can be private-only.

## Instagram Reels

Use a Meta app with Instagram API and Instagram Login, plus an Instagram
Business or Creator account. Register the callback below and save the **Instagram App ID and Instagram App Secret** from
Meta’s **API setup with Instagram login**, rather than the parent Facebook app credentials, inside VYRA.
Development-mode accounts must accept their Instagram tester invitation. Approve basic profile and content publishing access.

`https://vyra-five-lac.vercel.app/api/instagram-callback`

Connecting an account and uploading media are separate steps. Instagram must
fetch the clip from a reachable URL. The existing publisher uses temporary
signed URLs from a private R2 staging bucket, which must be configured before
posting. Open **Instagram App settings → Temporary video storage** and save the Cloudflare account ID, R2 bucket, and Object Read & Write S3 credentials. These settings stay in the local encrypted vault; no environment-file editing is required. Existing R2 environment settings still take precedence. Local clips remain available while hosting is absent.

VYRA retains the temporary file during media processing. The background worker polls the existing container once per minute and claims publication once after it finishes; restarting never creates a second upload. Interrupted publication requires review. Temporary files are deleted after Meta consumes them or after their 24-hour container window expires (with a one-hour buffer). Failed deletions remain recorded and retry while VYRA is running. Add an R2 lifecycle rule expiring the **vyra-publishing/** prefix after two days as a fallback when the PC stays off. The app does not edit bucket lifecycle rules automatically.

Local exports are removed ten minutes after all queued destinations confirm publication. Queued/sending/uncertain posts and unsent drafts retain the file. Original user videos outside the app, posts on social platforms, and publishing history are not deleted.

Instagram direct resumable upload is restricted to the Facebook Login for Business path; this app uses Instagram Login, so it deliberately keeps the temporary-URL method. A saved connection is not proof that storage credentials, app roles, or publishing permissions are valid. The worker reports those stages separately.

## Facebook Reels

Use a Meta app with Facebook Login and these Page permissions:
`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
Register the callback and save app details inside VYRA:

`https://vyra-five-lac.vercel.app/api/facebook-callback`

After authorizing, explicitly select the Page shown in VYRA. Personal Facebook
profiles are not destinations for this Page Reels publisher. Choose a vertical
9:16 clip of 4–60 seconds. Local binary uploads go directly to Meta. The queue
only sends a post after its destination, title, caption and consent are confirmed.
Provider errors and ambiguous outcomes stop for review rather than retrying.

App roles/test users and platform approvals can restrict which accounts can
authorize a developer app. VYRA does not bypass those restrictions. Meta's
callback relay and the local VYRA worker must be used from the same computer.
The relay forwards only state/code/error; local state validation happens before
token exchange. Credentials stay in the encrypted local vault. On Windows,
DPAPI wraps the vault's encryption key for the current user. Existing vaults
are migrated without discarding their stored connections.

Implementation references studied:

- [Google desktop OAuth and PKCE](https://developers.google.com/youtube/v3/guides/auth/installed-apps)
- [YouTube channels API](https://developers.google.com/youtube/v3/docs/channels/list)
- [Meta's Facebook Reels sample code](https://github.com/fbsamples/Facebook-Reels-Publishing-API-Postman-Collection)
- [Meta's Page token workflow](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/)

- [Meta content publishing and upload restrictions](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [Meta resumable upload prerequisites](https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads)
- [TikTok post-status confirmation](https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status)
