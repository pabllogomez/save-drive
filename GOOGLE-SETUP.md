# Google Cloud Console setup for Save Drive

Save Drive does **not** ship with OAuth credentials. You create your own
project in the Google Cloud Console and paste the credentials into the plugin.
This keeps your data under your control and avoids Google verification
requirements.

## Steps

1. Open https://console.cloud.google.com/ and sign in with the Google account
   that owns your Drive.

2. Create a new project (top-left project selector → **New Project**). Name it
   anything, e.g. "Save Drive".

3. Enable the Google Drive API:
   - Menu → **APIs & Services** → **Library**.
   - Search **Google Drive API** and click **Enable**.

4. Configure the OAuth consent screen:
   - **APIs & Services** → **OAuth consent screen**.
   - Choose **External**.
   - Fill in the required fields (App name = "Save Drive", user support email
     = your email, developer contact email = your email).
   - On **Scopes**, click **Add or Remove Scopes**, find
     `.../auth/drive.file`, and select it. This scope lets the app access only
     files it creates.
   - On **Test users**, click **Add users** and add your own Google email.
   - Finish.

5. Create OAuth credentials:
   - **APIs & Services** → **Credentials**.
   - **Create credentials** → **OAuth client ID**.
   - Application type: **TVs and Limited Input devices**.
   - Name: "Save Drive".
   - You will see a **Client ID** and **Client Secret**. Copy both.

6. In the plugin, paste them into **Client ID** and **Client Secret**, then
   tap **Sign in with Google**.

## Notes

- You do **not** need to publish the app for verification. `drive.file` is a
  non-sensitive scope; keeping it in testing mode with you as the only test
  user is enough.
- The plugin stores the refresh token locally on the Deck. No credential is
  uploaded anywhere besides Google's OAuth endpoint.
