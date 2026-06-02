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

## WhatsApp Templates

The system supports **9 approved Meta WhatsApp templates**. Each template has fixed parameters that must be provided when creating a campaign.

### Template Reference

| Template Name           | Parameters | Use Case                    |
| ----------------------- | ---------- | --------------------------- |
| `payment_reminder`      | 4 params   | Invoice payment reminders   |
| `invoice`               | 6 params   | Invoice notifications       |
| `sale`                  | 6 params   | Order confirmations         |
| `hello_world`           | 0 params   | Testing/onboarding          |
| `pos_marketing`         | Custom     | Point of Sale marketing     |
| `pos_receipt`           | Custom     | POS Receipt                 |
| `payment_receipt`       | Custom     | Payment Receipt             |
| `payment_link`          | Custom     | Payment Link                |
| `point_sale_marketing`  | Custom     | Point of Sale Marketing     |

### Contact Placeholder Substitution

When creating campaigns, use these placeholders in `template_components` to dynamically insert contact data:

- `{{contact_name}}` → Contact's full name from Odoo
- `{{contact_phone}}` → Contact's phone number
- `{{contact_email}}` → Contact's email address (empty string if not set)

These are substituted per-contact before sending.

---

## API Reference

### Health

| Method | Path | Description  |
| ------ | ---- | ------------ |
| GET    | `/`  | Health check (instant) |
| GET    | `/health/db` | Database connectivity check |

### Contacts

| Method | Path             | Description                                     |
| ------ | ---------------- | ----------------------------------------------- |
| POST   | `/contacts/sync` | Pull contacts from Odoo into PostgreSQL         |
| POST   | `/contacts/`     | Create a new contact in Odoo and local database |
| GET    | `/contacts/`     | List all local contacts                         |
| GET    | `/contacts/{id}` | Get a specific contact by ID                    |
| PUT    | `/contacts/{id}` | Update contact in Odoo and local database       |

**POST /contacts/sync** — Sync Odoo contacts into local database:

```bash
curl -X POST http://localhost:8000/contacts/sync
```

Response:
```json
{
  "created": 145,
  "updated": 5,
  "skipped": 0,
  "total": 150
}
```

**POST /contacts/** — Create a new contact (creates in Odoo first, then locally):

```bash
curl -X POST http://localhost:8000/contacts/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mohammad Imran",
    "phone": "918446998579",
    "email": "imran@example.com"
  }'
```

Response:
```json
{
  "id": 201,
  "name": "Mohammad Imran",
  "phone": "918446998579",
  "email": "imran@example.com",
  "odoo_partner_id": 5432,
  "last_synced_at": "2026-06-02T14:30:00",
  "created_at": "2026-06-02T14:30:00"
}
```

**GET /contacts/** — List all contacts:

```bash
curl http://localhost:8000/contacts/
```

Response:
```json
[
  {
    "id": 1,
    "name": "Mohammad Imran",
    "phone": "918446998579",
    "email": "user@example.com",
    "odoo_partner_id": 5432,
    "last_synced_at": "2026-06-02T10:30:00",
    "created_at": "2026-06-02T10:30:00"
  }
]
```

**GET /contacts/{id}** — Get a specific contact:

```bash
curl http://localhost:8000/contacts/1
```

Response (same as above):
```json
{
  "id": 1,
  "name": "Mohammad Imran",
  "phone": "918446998579",
  "email": "user@example.com",
  "odoo_partner_id": 5432,
  "last_synced_at": "2026-06-02T10:30:00",
  "created_at": "2026-06-02T10:30:00"
}
```

**PUT /contacts/{id}** — Update a contact (updates in Odoo first, then locally):

```bash
curl -X PUT http://localhost:8000/contacts/1 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mohammad Imran Updated",
    "phone": "919876543210",
    "email": "newemail@example.com"
  }'
```

All fields are optional — only provided fields will be updated:

```bash
curl -X PUT http://localhost:8000/contacts/1 \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "919876543210"
  }'
```

Response:
```json
{
  "id": 1,
  "name": "Mohammad Imran",
  "phone": "919876543210",
  "email": "newemail@example.com",
  "odoo_partner_id": 5432,
  "last_synced_at": "2026-06-02T14:35:00",
  "created_at": "2026-06-02T10:30:00"
}
```

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

#### POST /campaigns/ — Create campaign

**Payment Reminder** (4 parameters):
```bash
curl -X POST http://localhost:8000/campaigns/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Payment Reminder June 2026",
    "topic": "Outstanding Invoice Reminder",
    "template_name": "payment_reminder",
    "template_language": "en",
    "template_components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "{{contact_name}}"},
          {"type": "text", "text": "INR"},
          {"type": "text", "text": "5000"},
          {"type": "text", "text": "Flexmind Innovations"}
        ]
      }
    ]
  }'
```

**Invoice** (6 parameters):
```bash
curl -X POST http://localhost:8000/campaigns/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Invoice Notification June 2026",
    "topic": "Invoice Payment Notification",
    "template_name": "invoice",
    "template_language": "en",
    "template_components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "{{contact_name}}"},
          {"type": "text", "text": "INV/2026/00001"},
          {"type": "text", "text": "Flexmind Innovations"},
          {"type": "text", "text": "₹"},
          {"type": "text", "text": "5000"},
          {"type": "text", "text": "https://flexmindinnovations.odoo.com/my/invoices"}
        ]
      }
    ]
  }'
```

**Sale Order** (6 parameters):
```bash
curl -X POST http://localhost:8000/campaigns/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sale Order Confirmation June 2026",
    "topic": "Sales Order Confirmed",
    "template_name": "sale",
    "template_language": "en",
    "template_components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "{{contact_name}}"},
          {"type": "text", "text": "SO/2026/00001"},
          {"type": "text", "text": "Flexmind Innovations"},
          {"type": "text", "text": "₹"},
          {"type": "text", "text": "12000"},
          {"type": "text", "text": "https://flexmindinnovations.odoo.com/my/orders"}
        ]
      }
    ]
  }'
```

**Hello World** (no parameters):
```bash
curl -X POST http://localhost:8000/campaigns/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Hello World Test",
    "topic": "Test Campaign",
    "template_name": "hello_world",
    "template_language": "en"
  }'
```

Response (all):
```json
{
  "id": 1,
  "name": "Payment Reminder June 2026",
  "topic": "Outstanding Invoice Reminder",
  "template_name": "payment_reminder",
  "template_language": "en",
  "template_components": [...],
  "status": "draft",
  "scheduled_at": null,
  "created_at": "2026-06-02T10:30:00",
  "updated_at": "2026-06-02T10:30:00"
}
```

#### GET /campaigns/ — List all campaigns

```bash
curl http://localhost:8000/campaigns/
```

Response:
```json
[
  {
    "id": 1,
    "name": "Payment Reminder June 2026",
    "status": "completed",
    "template_name": "payment_reminder",
    "created_at": "2026-06-02T10:30:00",
    "updated_at": "2026-06-02T11:45:00"
  }
]
```

#### POST /campaigns/{id}/start — Start a campaign

```bash
curl -X POST http://localhost:8000/campaigns/1/start
```

Response:
```json
{
  "id": 1,
  "status": "running",
  "message": "Campaign started. Background job is processing..."
}
```

#### GET /campaigns/{id}/analytics — Campaign analytics

```bash
curl http://localhost:8000/campaigns/1/analytics
```

Response:
```json
{
  "campaign_id": 1,
  "campaign_name": "Payment Reminder June 2026",
  "status": "completed",
  "total_contacts": 150,
  "pending": 0,
  "sent": 145,
  "delivered": 138,
  "read": 92,
  "failed": 5,
  "delivery_rate": 0.92,
  "read_rate": 0.613
}
```

#### GET /campaigns/{id}/messages — Message records

```bash
curl http://localhost:8000/campaigns/1/messages?skip=0&limit=10
```

Response:
```json
[
  {
    "id": 1,
    "campaign_id": 1,
    "contact_id": 5,
    "whatsapp_message_id": "wamid.xxx",
    "delivery_status": "delivered",
    "sent_at": "2026-06-02T10:35:00",
    "error_message": null,
    "retry_count": 1,
    "created_at": "2026-06-02T10:30:00"
  }
]
```

### Webhooks

| Method | Path                 | Description                                         |
| ------ | -------------------- | --------------------------------------------------- |
| GET    | `/webhooks/whatsapp` | WhatsApp webhook verification handshake             |
| POST   | `/webhooks/whatsapp` | Receive delivery status + incoming message events   |

**Webhook Verification** (Meta sends this to verify your endpoint):
```bash
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=YOUR_VERIFY_TOKEN"
```

**Webhook Events** (Meta sends delivery status updates):
Meta will POST delivery updates to this endpoint automatically. No manual action required.

Example incoming webhook payload (delivery update):
```json
{
  "entry": [{
    "changes": [{
      "value": {
        "statuses": [{
          "id": "wamid.xxx",
          "status": "delivered",
          "timestamp": "1234567890"
        }]
      }
    }]
  }]
}
```

---

## Database Schema

### contacts table

Synced from Odoo via `/contacts/sync` endpoint.

```sql
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(20) NOT NULL UNIQUE,
    email VARCHAR(255),
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### campaigns table

Stores campaign metadata and configuration.

```sql
CREATE TABLE campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    topic TEXT,
    template_name VARCHAR(255) NOT NULL,
    template_language VARCHAR(10) DEFAULT 'en',
    template_components JSONB,
    status VARCHAR(50) DEFAULT 'draft',
    scheduled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Statuses:** `draft` → `scheduled` (if future scheduled_at) or `draft` → `running` → `completed`/`failed`

**template_components JSON structure:**

```json
[
  {
    "type": "body",
    "parameters": [
      {"type": "text", "text": "value1"},
      {"type": "text", "text": "value2"},
      ...
    ]
  }
]
```

### campaign_messages table

Per-contact message delivery tracking. Created when campaign starts.

```sql
CREATE TABLE campaign_messages (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    whatsapp_message_id VARCHAR(255),
    delivery_status VARCHAR(50) DEFAULT 'pending',
    sent_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Delivery Statuses:** `pending` → `sent` → `delivered` → `read` (or `failed` at any point)

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

---

## Deployment

### Render + Supabase

This system is designed to run on [Render](https://render.com) with [Supabase](https://supabase.com) PostgreSQL backend.

#### 1. Supabase Setup

1. Create a Supabase project
2. Get your PostgreSQL connection string from **Settings → Database**
3. Use the **Transaction Pooler** connection string (port 6543 instead of 5432) to avoid connection exhaustion under APScheduler
4. Copy the `DATABASE_URL` for `.env`

#### 2. Environment Variables

Create a `.env` file with:

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

# PostgreSQL (Supabase Transaction Pooler)
DATABASE_URL=postgresql://user:pass@db.supabase.co:6543/postgres

# Campaign tuning (optional)
CAMPAIGN_BATCH_SIZE=50
MESSAGE_DELAY_SECONDS=1
MAX_RETRY_ATTEMPTS=3
```

#### 3. Render Deployment

Create `render.yaml` in your repo root:

```yaml
services:
  - type: web
    name: whatsapp-campaigns
    env: python
    plan: standard
    region: oregon
    buildCommand: pip install uv && uv sync && uv run alembic upgrade head
    startCommand: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"

  - type: cron
    name: scheduler-cleanup
    schedule: "0 */6 * * *"
    runCommand: curl https://your-app.onrender.com/health/db

envVars:
  - key: ODOO_URL
    sync: false
  - key: ODOO_DB
    sync: false
  - key: ODOO_USERNAME
    sync: false
  - key: WHATSAPP_TOKEN
    sync: false
  - key: WHATSAPP_PHONE_NUMBER_ID
    sync: false
  - key: WHATSAPP_WEBHOOK_VERIFY_TOKEN
    sync: false
  - key: DATABASE_URL
    sync: false
```

#### 4. Deploy Steps

1. Push your code to GitHub
2. Create a new service on Render
3. Connect your GitHub repo
4. Paste environment variables (from `.env`)
5. Render will run `buildCommand` automatically on each deploy
6. Migrations run before the service starts
7. APScheduler will initialize on startup

#### 5. Webhook Configuration (Meta)

After deployment:

1. Go to **Meta Developer Console → WhatsApp → Configuration**
2. Set **Callback URL** to `https://your-app.onrender.com/webhooks/whatsapp`
3. Set **Verify Token** to value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
4. Subscribe to **messages** and **message_status_updates** webhooks

#### 6. Monitor Logs

View logs in Render dashboard:

- **Events** tab: deployment progress
- **Logs** tab: application output, errors, scheduled tasks

#### 7. Health Checks

- `GET /` — instant health check
- `GET /health/db` — database connectivity check
- Render's probe calls `GET /` every 30 seconds

#### 8. Troubleshooting Deployment

##### Build fails: ModuleNotFoundError

- Ensure `pyproject.toml` is in repo root (not in `app/` subdirectory)
- Check Render "Root Directory" is empty (not set to `app/`)

##### Database migration hangs

- Use Supabase Transaction Pooler (port 6543), not standard pooler (5432)
- Verify `DATABASE_URL` in environment variables
- Check Supabase database is not in pause state

##### APScheduler errors

- Jobs use MemoryJobStore (not database) to avoid connection at startup
- Scheduled campaigns survive restarts only if job was persisted before restart
- For critical scheduled campaigns, use `/campaigns/{id}/start` endpoint instead

##### Webhook not receiving events

- Verify **Callback URL** is reachable from internet (`curl https://your-app.onrender.com/webhooks/whatsapp?hub.mode=subscribe`)
- Check **Verify Token** matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
- Ensure webhooks are **subscribed** in Meta console
