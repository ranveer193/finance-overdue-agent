from core.models import InvoiceData
from path import Path
import pandas as pd
from datetime import datetime,timezone
from dateutil.parser import parse
import hashlib
from pathlib import Path
from core.config import *

def generate_payment_link(invoice_no: str) -> str:
    return f"https://pay.company.com/{invoice_no}"

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""

    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[:2] + "*" * (len(local) - 2)

    return f"{masked_local}@{domain}"

def build_subject(
    template: str,
    invoice: InvoiceData,
    days_overdue: int,
) -> str:
    formatted_amount = f"{invoice['amount']:,.0f}"

    return template.format(
        invoice_no=invoice["invoice_no"],
        amount=formatted_amount,
        days_overdue=days_overdue,
    )

def load_csv (csv_path):
    if not csv_path:
        raise ValueError("csv_path is required")

    path = Path(csv_path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    if path.suffix.lower() != ".csv":
        raise ValueError("Input file must be a CSV")

    df = pd.read_csv(path)

    if df.empty:
        raise ValueError("CSV file is empty")

    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing_columns))}"
        )

    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")

def get_overdue_days (due_date):
    try:
        due_date = parse(str(due_date), dayfirst=True).date()
        today = datetime.today().date()
        days_overdue = max((today - due_date).days, 0)
        return days_overdue
    except Exception as e:
        print(f"Invalid date format: {due_date}")
        return None
    
def get_stage_meta (days):
    if days == 0:
        return {
            "stage_key": "No_overdue",
            "stage_meta" : {
                "followup_number": 0,
                "tone": "No Action Required",
                "key_message": "Invoice is not overdue.",
                "cta": "No action required.",
                "escalation_required": False,
                "subject_template": "",
            }
        }
    
    if 1 <= days <= 7:
        stage = "1st Follow-Up"
    elif 8 <= days <= 14:
        stage = "2nd Follow-Up"
    elif 15 <= days <= 21:
        stage = "3rd Follow-Up"
    elif 22 <= days <= 30:
        stage = "4th Follow-Up"
    else:
        stage = "Escalation Flag"
    
    return {
        "stage_key": stage,
        "stage_meta": stage_values[stage]
    }

RETRYABLE_ERRORS = (
        "429",
        "rate limit",
        "capacity exceeded",
        "service tier capacity exceeded",
        "timeout",
        "temporarily unavailable",
        "connection error",
        'maximum retry attempts'
    )

def is_retryable_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(pattern in message for pattern in RETRYABLE_ERRORS)

def compute_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()

    with Path(file_path).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()

def format_currency(amount) -> str:
    """
    Format numeric amounts as INR unless a currency code/symbol
    is already present in the input string.
    """
    if isinstance(amount, str):
        amount = amount.strip()

        currency_prefixes = (
            "INR", "USD", "EUR", "GBP",
            "₹", "$", "€", "£"
        )

        if amount.startswith(currency_prefixes):
            return amount

        amount = float(amount)

    return f"INR {float(amount):,.2f}"
