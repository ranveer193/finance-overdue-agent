from core.models import StageKey,StageMeta
import os

stage_values: dict[StageKey, StageMeta] = {
    "1st Follow-Up": {
        "followup_number": 1,
        "tone": "Warm & Friendly",
        "key_message": "This appears to be a friendly reminder in case the invoice was overlooked.",
        "cta": "Please complete the payment at your earliest convenience.",
        "escalation_required": False,
        "subject_template": (
            "Quick Reminder – Invoice #{invoice_no} | ₹{amount} Due"
        )
    },
    "2nd Follow-Up": {
        "followup_number": 2,
        "tone": "Polite but Firm",
        "key_message": "The payment is still pending and we would appreciate an update.",
        "cta": "Please confirm your expected payment date.",
        "escalation_required": False,
        "subject_template": (
            "Payment Follow-Up – Invoice #{invoice_no} "
            "({days_overdue} Days Overdue)"
        )
    },
    "3rd Follow-Up": {
        "followup_number": 3,
        "tone": "Formal & Serious",
        "key_message": "The invoice remains unpaid and requires immediate attention.",
        "cta": "Please respond within 48 hours.",
        "escalation_required": False,
         "subject_template": (
            "IMPORTANT: Outstanding Payment – Invoice "
            "#{invoice_no} ({days_overdue} Days Overdue)"
        ),
    },
    "4th Follow-Up": {
        "followup_number": 4,
        "tone": "Stern & Urgent",
        "key_message": "This is a final reminder before escalation.",
        "cta": "Please make payment immediately or contact us.",
        "escalation_required": False,
          "subject_template": (
            "FINAL NOTICE – Invoice #{invoice_no} – "
            "Immediate Action Required"
        ),
    },
    "Escalation Flag": {
        "followup_number": 5,
        "tone": "Legal Review Required",
        "key_message": "The case requires human review.",
        "cta": "Assign to finance manager.",
        "escalation_required": True,
         "subject_template": (
            "Escalation Required – Invoice #{invoice_no}"
        ),
    }
}

REQUIRED_COLUMNS = {
    "client_name",
    "recipient_email",
    "invoice_number",
    "amount",
    "due_date"
}

MAX_RETRY_ATTEMPTS = int(
    os.getenv("WORKER_MAX_RETRY_ATTEMPTS", 5)
)

INITIAL_BACKOFF_SECONDS = int(
    os.getenv("WORKER_INITIAL_BACKOFF_SECONDS", 2)
)

DELAY_BETWEEN_INVOICES = float(
    os.getenv("WORKER_DELAY_BETWEEN_INVOICES", 1)
)

# Background scheduler settings
FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES = int(
    os.getenv("FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES", "2")
)

FAILED_INVOICE_BATCH_SIZE = int(
    os.getenv("FAILED_INVOICE_BATCH_SIZE", "100")
)

FAILED_INVOICE_MAX_BACKOFF_MINUTES = int(
    os.getenv("FAILED_INVOICE_MAX_BACKOFF_MINUTES", "60")
)

FAILED_INVOICE_SCHEDULER_TIMEZONE = os.getenv(
    "FAILED_INVOICE_SCHEDULER_TIMEZONE",
    "UTC",
)

FAILED_INVOICE_SCHEDULER_MISFIRE_GRACE_SECONDS = int(
    os.getenv(
        "FAILED_INVOICE_SCHEDULER_MISFIRE_GRACE_SECONDS",
        "60",
    )
)