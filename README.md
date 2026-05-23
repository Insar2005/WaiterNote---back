# Waiter Note — Backend

FastAPI + async SQLAlchemy + Postgres. Auth via Telegram WebApp initData.

## Project layout

```
backend/
├── main.py              # FastAPI app + router wiring
├── models.py            # SQLAlchemy ORM (lives at project root, copy here for runtime)
├── config.py            # env-based settings
├── deps.py              # DI: get_session, get_current_user, workplace access
├── auth.py              # Telegram initData HMAC validation
├── schemas/             # Pydantic DTOs
├── services/            # transactional business logic (no commits)
├── routers/             # HTTP endpoints
└── utils/
    ├── ids.py           # nanoid format validator
    └── time.py          # utc_ts helper
```

## Setup

```bash
# Place models.py at the same level as main.py (or adjust imports)
cp ../models.py .

pip install -r requirements.txt
cp .env.example .env
# Edit .env: set BOT_TOKEN, DATABASE_URL, CORS_ORIGINS

uvicorn main:app --reload
```

OpenAPI docs at `http://localhost:8000/docs`.

## Auth

Every endpoint (except none — `/me` is the only "open"-ish one) requires header:

```
X-Init-Data: <Telegram.WebApp.initData>
```

The first request creates the user automatically. No `/register` flow.

## API overview

| Resource | Endpoints |
|---|---|
| Me | `GET/PATCH /me` |
| Workplaces | `GET/POST/PATCH/DELETE /workplaces`, `/archive`, `/select`, `/reorder` |
| Halls | `GET/POST /workplaces/{w}/halls`, `PATCH/DELETE /halls/{h}` |
| Tables | `POST /halls/{h}/tables`, `PATCH/DELETE /tables/{t}` |
| Menu | `GET/POST /workplaces/{w}/menu/...`, `PATCH/DELETE /menu/categories/{c}`, `/items/{i}` |
| Shifts | `GET/POST /workplaces/{w}/shifts`, `/current`, `POST /shifts/{s}/close`, `/recompute` |
| Orders | `GET/POST /shifts/{s}/orders`, `/workplaces/{w}/orders` (quick), CRUD on `/orders/{o}`, `/items`, `/move`, `/pay` |
| Notes | `GET/POST/PATCH/DELETE /notes` |

## Conventions

- **All IDs are nanoid(21), generated on the client.**
- `ondelete=CASCADE` cleans up children; orders/items survive menu/table deletion via snapshots.
- Services don't commit; routers do. Composability is the win.
- One open shift per (workplace, user) — enforced via partial unique index.