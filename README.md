# WhatsApp Campaign Management System

A production-ready bulk WhatsApp messaging platform built with FastAPI. Syncs contacts from Odoo ERP and sends personalised WhatsApp template messages via Meta's Cloud API — with campaign scheduling, background processing, retry logic, and delivery tracking.

---

## Tech Stack

| Layer       | Technology                         |
| ----------- | ---------------------------------- |
| API         | FastAPI + Uvicorn                  |
| Database    | PostgreSQL + SQLAlchemy 2.0        |
| Migrations  | Alembic                            |
| Scheduling  | APScheduler (SQLAlchemy job store) |
| Config      | Pydantic-Settings v2               |
| Messaging   | Meta WhatsApp Cloud API v25.0      |
| CRM         | Odoo XML-RPC                       |

---

## Project Structure

```text
app/
├── main.py                  # FastAPI app, lifespan, router registration
├── config.py                # Pydantic settings (loaded from .env)
├── database.py              # SQLAlchemy engine + session factory
│
├── models/
│   ├── contact.py           # Contact (synced from Odoo)
│   ├── campaign.py          # Campaign + CampaignStatus enum
│   └── campaign_message.py  # Per-contact message record + DeliveryStatus enum
│
├── schemas/
│   ├── contact.py           # ContactOut, SyncResult
│   └── campaign.py          # CampaignCreate, CampaignOut, CampaignAnalytics …
│
├── services/
│   ├── odoo_service.py      # XML-RPC contact sync
│   ├── whatsapp_service.py  # Meta Graph API (send_template, send_text)
│   ├── campaign_service.py  # Campaign CRUD + analytics
│   └── scheduler_service.py # APScheduler init / shutdown
│
├── jobs/
│   └── campaign_job.py      # Background execution: batch send + retry
│
├── routers/
│   ├── campaigns.py         # /campaigns endpoints
│   ├── contacts.py          # /contacts endpoints
│   └── whatsapp.py          # /webhooks/whatsapp (verify + events)
│
└── utils/
    └── logging.py           # JSON structured logging
```

---

## Setup

### 1. Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- PostgreSQL running locally (or update `DATABASE_URL`)

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure environment

Edit `.env` with your credentials:

```env
# Odoo
ODOO_URL=https://your-instance.odoo.com
ODOO_DB=your_db
ODOO_USERNAME=user@example.com
ODOO_PASSWORD=your_password

# WhatsApp Cloud API
WHATSAPP_TOKEN=your_bearer_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your_secret_token

# PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost:5432/whatsapp_campaigns

# Campaign tuning (optional — these are the defaults)
CAMPAIGN_BATCH_SIZE=50
MESSAGE_DELAY_SECONDS=1
MAX_RETRY_ATTEMPTS=3
```

### 4. Create the database

```bash
createdb whatsapp_campaigns
```

### 5. Run migrations

```bash
uv run alembic upgrade head
```

### 6. Start the server

```bash
uv run uvicorn app.main:app --reload
```

API docs: <http://localhost:8000/docs>

---

## API Reference

### Health

| Method | Path | Description  |
| ------ | ---- | ------------ |
| GET    | `/`  | Health check |

### Contacts

| Method | Path             | Description                              |
| ------ | ---------------- | ---------------------------------------- |
| POST   | `/contacts/sync` | Pull contacts from Odoo into PostgreSQL  |
| GET    | `/contacts/`     | List all local contacts                  |

### Campaigns

| Method | Path                          | Description                                        |
| ------ | ----------------------------- | -------------------------------------------------- |
| POST   | `/campaigns/`                 | Create a campaign (draft or scheduled)             |
| GET    | `/campaigns/`                 | List all campaigns                                 |
| GET    | `/campaigns/{id}`             | Get campaign details                               |
| POST   | `/campaigns/{id}/start`       | Start immediately (returns instantly, runs in BG)  |
| POST   | `/campaigns/{id}/cancel`      | Cancel a draft / scheduled / running campaign      |
| GET    | `/campaigns/{id}/messages`    | Per-contact message records                        |
| GET    | `/campaigns/{id}/analytics`   | Delivery analytics                                 |

### Webhooks

| Method | Path                 | Description                                         |
| ------ | -------------------- | --------------------------------------------------- |
| GET    | `/webhooks/whatsapp` | WhatsApp webhook verification handshake             |
| POST   | `/webhooks/whatsapp` | Receive delivery status + incoming message events   |

---

## Campaign Lifecycle

```text
POST /campaigns             → status: draft | scheduled
POST /campaigns/{id}/start
        ↓
  Contacts fetched from DB
        ↓
  CampaignMessage rows created (status: pending)
        ↓
  Campaign status → running  (API returns immediately)
        ↓
  Background job starts
        ↓
  Send in batches of CAMPAIGN_BATCH_SIZE
  with MESSAGE_DELAY_SECONDS between messages
        ↓
  Per message: up to MAX_RETRY_ATTEMPTS
  with exponential backoff (2 s, 4 s)
        ↓
  Campaign status → completed | failed
```

Webhook events from Meta update each message's `delivery_status` to `delivered` / `read` / `failed`.

---

## Scheduled Campaigns

Pass `scheduled_at` (ISO 8601 UTC) when creating. If it is in the future the campaign is created with status `scheduled` and APScheduler fires it automatically — surviving server restarts via its SQLAlchemy job store.

```json
POST /campaigns
{
  "name": "Payment Reminder June",
  "topic": "Outstanding Invoice Reminder",
  "template_name": "payment_reminder",
  "scheduled_at": "2026-06-10T10:00:00"
}
```

---

## Webhook Setup (Meta Developer Console)

1. Set **Callback URL** → `https://your-domain.com/webhooks/whatsapp`
2. Set **Verify Token** → value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `.env`
3. Subscribe to **messages** and **message_status_updates**

---

## Delivery Analytics

```json
GET /campaigns/{id}/analytics

{
  "campaign_id": 1,
  "campaign_name": "Payment Reminder June",
  "status": "completed",
  "total_contacts": 200,
  "pending": 0,
  "sent": 195,
  "delivered": 180,
  "read": 120,
  "failed": 5,
  "delivery_rate": 0.9,
  "read_rate": 0.6
}
```

---

## AI Integration (Future)

The codebase has two clearly marked extension points:

- **`app/jobs/campaign_job.py → _build_components()`** — replace with an AI service call that uses `campaign.topic` to generate personalised message variables per contact
- **`app/routers/whatsapp.py → _handle_incoming_message()`** — pipe incoming customer messages to OpenAI / Claude, then call `WhatsAppService().send_text()` with the generated reply

No other changes to the system are required.

---

## Migrations

After changing a model, auto-generate a migration:

```bash
uv run alembic revision --autogenerate -m "describe your change"
uv run alembic upgrade head
```

Rollback one step:

```bash
uv run alembic downgrade -1
```
