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
Business or Creator account. Register the callback below and save the app ID
and secret inside VYRA. Approve basic profile and content publishing access.

`https://vyra-five-lac.vercel.app/api/instagram-callback`

Connecting an account and uploading media are separate steps. Instagram must
fetch the clip from a reachable URL. The existing publisher uses temporary
signed URLs from a private R2 staging bucket, which must be configured before
posting. Local clips remain available for manual upload while hosting is absent.

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
