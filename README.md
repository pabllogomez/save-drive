# Save Drive

Decky Loader plugin that backs up your Steam Deck game saves to your own
Google Drive. Covers both Steam and non-Steam games.

> v1 is **backup-only** (Deck → Drive). Restore is manual and always archives
> your current local save first, so a wrong restore is reversible.

## How it works

- Before the Deck sleeps or shuts down, the plugin holds a `systemd-inhibit`
  block, runs a backup of enabled games, then releases the inhibitor.
- Saves are zipped and uploaded to a `SaveDrive/<game-id>/` folder in your
  Drive.
- It keeps only the latest N snapshots per game (configurable).
- Login uses Google OAuth **device-code flow** — no browser needed in Game
  Mode.

## Setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/):
   - Enable the **Google Drive API**.
   - OAuth consent screen → **External**, add yourself as a **test user**.
   - Credentials → **Create OAuth client ID** → type **TVs and Limited Input
     devices**.
   - Copy `client_id` and `client_secret`.

2. On the Deck, install the plugin in Decky Loader (Developer mode → Install
   plugin from URL).

3. Open **Save Drive** in the Quick Access menu, paste your credentials and
   tap **Sign in with Google**. The plugin shows a code; go to
   `https://g.co/device` on your phone/PC and type the code.

4. Enable the games you want backed up and, if needed, set the exact save
   paths (comma separated). The plugin auto-detects Steam `userdata/` and
   Proton prefixes.

## Development

```bash
pnpm install
pnpm run build
pnpm run package   # creates installable zip in out/
```

Backend code lives in `main.py` and `py_modules/savedrive/` and uses only the
Python standard library.

## License

BSD-3-Clause
