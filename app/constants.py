"""
Application Constants

Centralized file for all magic strings, numbers, and configuration values.
Import and use these constants throughout the application instead of hardcoding values.

Categories:
- Odoo Models
- Odoo Fields
- Odoo Actions
- API Timeouts
- API Defaults
- Campaign Constants
- Message Constants
- Invoice Constants
- Contact Constants
- WhatsApp Constants
- Validation Constants
"""

# ============================================================================
# ODOO MODELS
# ============================================================================
class OdooModels:
    """Odoo model names"""
    ACCOUNT_MOVE = "account.move"
    ACCOUNT_INVOICE = "account.invoice"
    ACCOUNT_MOVE_LINE = "account.move.line"
    ACCOUNT_PAYMENT = "account.payment"
    RES_PARTNER = "res.partner"
    SALE_ORDER = "sale.order"
    SALE_ORDER_LINE = "sale.order.line"
    IR_ACTIONS_REPORT = "ir.actions.report"
    COMMON = "common"


# ============================================================================
# ODOO FIELDS - Partner/Contact
# ============================================================================
class OdooFieldsPartner:
    """Fields for res.partner (contacts)"""
    ID = "id"
    NAME = "name"
    PHONE = "phone"
    EMAIL = "email"
    COMPANY_ID = "company_id"


# ============================================================================
# ODOO FIELDS - Invoice/Account.Move
# ============================================================================
class OdooFieldsInvoice:
    """Fields for account.move (invoices)"""
    ID = "id"
    NAME = "name"
    INVOICE_DATE = "invoice_date"
    INVOICE_DATE_DUE = "invoice_date_due"   # Odoo 16+
    DUE_DATE = "due_date"                   # Odoo ≤15 alias
    PARTNER_ID = "partner_id"
    AMOUNT_TOTAL = "amount_total"
    STATE = "state"
    PAYMENT_STATE = "payment_state"
    MOVE_TYPE = "move_type"
    INVOICE_LINE_IDS = "invoice_line_ids"


# ============================================================================
# ODOO FIELDS - Invoice Line
# ============================================================================
class OdooFieldsInvoiceLine:
    """Fields for account.move.line (invoice lines)"""
    ID = "id"
    NAME = "name"
    QUANTITY = "quantity"
    PRICE_UNIT = "price_unit"
    PRICE_SUBTOTAL = "price_subtotal"


# ============================================================================
# ODOO FIELDS - Sale Order
# ============================================================================
class OdooFieldsSaleOrder:
    """Fields for sale.order"""
    ID = "id"
    NAME = "name"
    DATE_ORDER = "date_order"
    STATE = "state"
    AMOUNT_TOTAL = "amount_total"


# ============================================================================
# ODOO FIELDS - Account Payment
# ============================================================================
class OdooFieldsPayment:
    """Fields for account.payment"""
    ID = "id"
    NAME = "name"
    DATE = "date"
    AMOUNT = "amount"
    PARTNER_ID = "partner_id"
    STATE = "state"


# ============================================================================
# ODOO MOVE TYPES
# ============================================================================
class OdooMoveTypes:
    """Types of account.move records"""
    OUT_INVOICE = "out_invoice"
    OUT_REFUND = "out_refund"
    IN_INVOICE = "in_invoice"
    IN_REFUND = "in_refund"


# ============================================================================
# ODOO INVOICE STATES
# ============================================================================
class OdooInvoiceStates:
    """States for account.move (invoices)"""
    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"


# ============================================================================
# ODOO PAYMENT STATES
# ============================================================================
class OdooPaymentStates:
    """Payment states for account.move"""
    PAID = "paid"
    NOT_PAID = "not_paid"
    PARTIAL = "partial"
    REVERSED = "reversed"


# ============================================================================
# ODOO ACTIONS
# ============================================================================
class OdooActions:
    """Action methods in Odoo"""
    ACTION_POST = "action_post"
    RENDER_QWEB_PDF = "_render_qweb_pdf"
    AUTHENTICATE = "authenticate"
    SEARCH_READ = "search_read"
    READ = "read"
    CREATE = "create"
    WRITE = "write"
    EXECUTE_KW = "execute_kw"


# ============================================================================
# ODOO REPORT NAMES
# ============================================================================
class OdooReports:
    """Report names in Odoo"""
    ACCOUNT_REPORT_INVOICE = "account.report_invoice"


# ============================================================================
# API TIMEOUTS (in seconds)
# ============================================================================
class ApiTimeouts:
    """HTTP request timeouts"""
    DEFAULT = 30
    LONG_REQUEST = 60
    WHATSAPP_MEDIA_UPLOAD = 60
    ODOO_REPORT_RENDER = 30
    ODOO_PDF_FETCH = 30


# ============================================================================
# API DEFAULTS
# ============================================================================
class ApiDefaults:
    """Default values for API queries"""
    INVOICE_LIMIT = 5
    ORDER_LIMIT = 5
    PAYMENT_LIMIT = 3
    LIST_INVOICE_LIMIT = 100
    DEFAULT_OFFSET = 0


# ============================================================================
# ORDERING
# ============================================================================
class OrderByDirection:
    """Sort direction for Odoo queries"""
    DESCENDING = "DESC"
    ASCENDING = "ASC"


class OrderByField:
    """Field names for ordering"""
    INVOICE_DATE = "invoice_date DESC"
    DATE_ORDER = "date_order DESC"
    DATE = "date DESC"
    CREATED_AT = "created_at DESC"


# ============================================================================
# CAMPAIGN CONSTANTS
# ============================================================================
class CampaignDefaults:
    """Default values for campaigns"""
    BATCH_SIZE = 50
    MESSAGE_DELAY_SECONDS = 1.0
    MAX_RETRY_ATTEMPTS = 3
    RETRY_BACKOFF_BASE = 2  # Exponential backoff: 2^n seconds


class CampaignStatus:
    """Campaign statuses"""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


# ============================================================================
# MESSAGE CONSTANTS
# ============================================================================
class DeliveryStatus:
    """Message delivery statuses"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class MessageRole:
    """Message sender role"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ============================================================================
# INVOICE CONSTANTS
# ============================================================================
class InvoiceDefaults:
    """Default values for invoices"""
    CURRENCY = "INR"
    RUPEE_SYMBOL = "₹"


class InvoiceApi:
    """Invoice API constants"""
    PDF_ENDPOINT = "/api/invoice/pdf/"
    TEST_ENDPOINT = "/api/invoice/pdf/test"


# ============================================================================
# CONTACT CONSTANTS
# ============================================================================
class ContactSync:
    """Contact synchronization constants"""
    PHONE_PATTERN = r"^\+?[0-9\s\-\(\)]{10,}$"
    MIN_PHONE_LENGTH = 10
    EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"


# ============================================================================
# WHATSAPP CONSTANTS
# ============================================================================
class WhatsAppApi:
    """WhatsApp Cloud API constants"""
    BASE_URL = "https://graph.facebook.com/v25.0"
    API_VERSION = "v25.0"
    MESSAGE_TYPE_TEXT = "text"
    MESSAGE_TYPE_TEMPLATE = "template"
    MESSAGE_TYPE_DOCUMENT = "document"
    MESSAGING_PRODUCT = "whatsapp"
    RECIPIENT_TYPE = "individual"


class WhatsAppTemplate:
    """WhatsApp template constants"""
    DEFAULT_LANGUAGE = "en"
    PARAMETER_TYPE_TEXT = "text"
    PARAMETER_TYPE_MEDIA = "media"
    COMPONENT_TYPE_BODY = "body"
    COMPONENT_TYPE_HEADER = "header"


class WhatsAppMedia:
    """WhatsApp media upload constants"""
    TYPE_PDF = "document"
    MIME_TYPE_PDF = "application/pdf"
    MAX_FILE_SIZE_MB = 100


# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================
class ValidationErrors:
    """Error messages for validation"""
    INVALID_PHONE = "Invalid phone number format"
    INVALID_EMAIL = "Invalid email format"
    MISSING_REQUIRED_FIELD = "Missing required field"
    INVALID_STATUS = "Invalid status value"


class HttpStatusCodes:
    """HTTP status codes"""
    OK = 200
    CREATED = 201
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    INTERNAL_SERVER_ERROR = 500


# ============================================================================
# LOGGING CONSTANTS
# ============================================================================
class LogMessages:
    """Standard log messages"""
    # Odoo
    ODOO_CONTACT_CREATED = "Contact created in Odoo"
    ODOO_CONTACT_UPDATED = "Contact updated in Odoo"
    ODOO_CONTACT_SYNC_COMPLETE = "Odoo contact sync complete"
    ODOO_INVOICES_FETCHED = "Customer invoices fetched"
    ODOO_INVOICE_PDF_FETCHED = "Invoice PDF fetched successfully from Odoo API"
    ODOO_AUTH_FAILED = "Odoo authentication failed"
    ODOO_CONNECTION_FAILED = "Odoo connection failed"

    # Campaign
    CAMPAIGN_STARTED = "Campaign job started"
    CAMPAIGN_COMPLETED = "Campaign job completed"
    MESSAGE_SENT = "Message sent"
    MESSAGE_DELIVERY_FAILED = "Message failed after all retries"

    # WhatsApp
    WHATSAPP_MESSAGE_SENT = "WhatsApp message sent"
    WHATSAPP_MEDIA_UPLOADED = "Media uploaded to Meta successfully"
    WHATSAPP_DELIVERY_UPDATE = "WhatsApp delivery status update"

    # AI
    AI_RESPONSE_GENERATED = "AI response generated"
    AI_CONTEXT_BUILT = "Context built for AI prompt"


# ============================================================================
# FIELD MAPPING
# ============================================================================
class OdooQueries:
    """Common Odoo query patterns"""
    # Domain filters
    INVOICE_FILTER = [
        ["partner_id", "=", None],  # Placeholder, filled at runtime
        ["move_type", "in", ["out_invoice", "out_refund"]],
        ["payment_state", "!=", "paid"]
    ]

    SALE_ORDER_FILTER = [
        ["partner_id", "=", None],  # Placeholder
        ["state", "in", ["sale", "done"]]
    ]

    PARTNER_WITH_PHONE = [["phone", "!=", False]]


# ============================================================================
# CURRENCY SYMBOLS
# ============================================================================
class CurrencySymbols:
    """Currency symbols and formatting"""
    INR = "₹"
    USD = "$"
    EUR = "€"
    GBP = "£"


# ============================================================================
# DATABASE CONSTANTS
# ============================================================================
class DatabaseDefaults:
    """Database connection and query defaults"""
    QUERY_TIMEOUT = 30
    CONNECTION_POOL_SIZE = 10
    MAX_OVERFLOW = 20


# ============================================================================
# CAMPAIGN TEMPLATE DEFAULTS
# ============================================================================
class TemplateDefaults:
    """Default template names and settings"""
    HELLO_WORLD = "hello_world"
    PAYMENT_REMINDER = "payment_reminder"
    INVOICE_TEMPLATE = "invoice"


# ============================================================================
# PAGINATION CONSTANTS
# ============================================================================
class Pagination:
    """Pagination defaults"""
    DEFAULT_LIMIT = 50
    DEFAULT_SKIP = 0
    MAX_LIMIT = 100


# ============================================================================
# GEMINI AI CONSTANTS
# ============================================================================
class GeminiAi:
    """Google Gemini AI constants"""
    MODEL = "gemini-2.5-flash"
    MAX_OUTPUT_TOKENS = 1024
    TEMPERATURE = 0.7


# ============================================================================
# PHONE NUMBER FORMATTING
# ============================================================================
class PhoneFormatting:
    """Phone number formatting constants"""
    WHATSAPP_PREFIX = "91"  # India country code
    DIGIT_ONLY_PATTERN = r"\D"  # Non-digit characters
