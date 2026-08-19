# Multiverse Global Records — Website + Backend

## Run

1. Install Node.js 18+.
2. Open this folder in a terminal.
3. Run `npm install`.
4. Copy `.env.example` to `.env` and change the admin/developer passwords.
5. Run `npm start`.
6. Open `http://localhost:3000`.

## API

- `GET /api/health`
- `GET/POST /api/events`
- `GET/POST /api/notifications`
- `GET/POST /api/posts`
- `GET /api/sponsors`
- `GET /api/stats`
- `POST /api/registrations`
- `POST /api/auth/login`
- `POST /api/admin/verification/request`
- `POST /api/admin/verification/confirm`
- `POST /api/ei/ask`

The website already points to `/api`, so no frontend URL change is needed when the HTML and server run from the same host.

## YouTube

Set `YOUTUBE_API_KEY` in `.env` to make the EI learning assistant return real YouTube video IDs. Without it, the assistant returns useful YouTube search links, so the feature still works.

## Storage

This starter uses JSON files in `data/` and uploaded media in `uploads/`. For a production deployment with many concurrent users, move these to a proper database/object-storage layer.
