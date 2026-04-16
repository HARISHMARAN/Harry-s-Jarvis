# JARVIS Setup Placeholders

Use this file as the exact checklist for the pieces you need to replace.

## 1) Environment file

File: [.env.example](/Users/harishmaran/Documents/Harry's Jarvis/jarvis/.env.example)

Replace these values after copying it to `.env`:

- `ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY_HERE`
- `FISH_API_KEY=YOUR_FISH_AUDIO_API_KEY_HERE`
- `FISH_VOICE_ID=YOUR_FISH_VOICE_ID_HERE`
- `USER_NAME=Your Name`
- `HONORIFIC=sir`
- `CALENDAR_ACCOUNTS=auto`
- `GOOGLE_CLIENT_ID=YOUR_GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN=YOUR_GOOGLE_OAUTH_REFRESH_TOKEN`
- `GOOGLE_USER_EMAIL=you@gmail.com`
- `GOOGLE_CALENDAR_IDS=primary`
- `GOOGLE_TIMEZONE=Asia/Kolkata`

## 2) Settings panel

File: [frontend/src/settings.ts](/Users/harishmaran/Documents/Harry's Jarvis/jarvis/frontend/src/settings.ts)

The visible placeholders in the UI live here:

- Anthropic key input placeholder
- Fish Audio key input placeholder
- Fish Voice ID input placeholder
- Calendar accounts placeholder
- User name placeholder
- Google OAuth placeholders

## 3) Backend defaults and validation

File: [server.py](/Users/harishmaran/Documents/Harry's Jarvis/jarvis/server.py)

These are the values the app reads at runtime:

- `ANTHROPIC_API_KEY`
- `FISH_API_KEY`
- `FISH_VOICE_ID`
- `USER_NAME`
- `HONORIFIC`
- `CALENDAR_ACCOUNTS`

## 4) What you need to do

1. Copy `.env.example` to `.env`.
2. Paste in your Anthropic API key.
3. Paste in your Fish Audio API key.
4. Optionally set your Fish Voice ID.
5. Set your name and honorific.
6. Add calendar emails or leave `CALENDAR_ACCOUNTS=auto`.
7. Add Google OAuth values if you want Gmail and Google Calendar instead of Apple Mail/Calendar.
8. Start the backend and frontend.
