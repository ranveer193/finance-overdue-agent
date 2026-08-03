from typing import TypedDict, Literal, Optional, Any, List, Dict
from pydantic import BaseModel, Field, EmailStr
from langchain_mistralai import ChatMistralAI
from dotenv import load_dotenv
from core.prompts import EMAIL_PROMPT

load_dotenv()

class EmailDraft(BaseModel):
    recipient: EmailStr = Field(description="Recipient email address")
    subject: str = Field(description="Exact subject line provided by the workflow")
    greeting: str = Field(
        description="Opening salutation, e.g. 'Hi Rajesh,' or 'Dear Mr. Kapoor,'"
    )
    body: str = Field(
        description="Main email body containing invoice details and payment request"
    )
    closing: str = Field(
        description="Professional closing, e.g. 'Regards, Finance Team'"
    )
    tone: Literal[
        "Warm & Friendly",
        "Polite but Firm",
        "Formal & Serious",
        "Stern & Urgent",
        "Legal Review Required",
    ] = Field(description="Communication tone used in the email")


class InvoiceData(TypedDict):
    invoice_no: str
    client: str
    amount: float
    due_date: str
    contact_email: str
    followup_count: int


class StageMeta(TypedDict):
    followup_number: int
    tone: Literal[
        "Warm & Friendly",
        "Polite but Firm",
        "Formal & Serious",
        "Stern & Urgent",
        "Legal Review Required",
    ]
    key_message: str
    cta: str
    escalation_required: bool
    subject_template: str


StageKey = Literal[
    "1st Follow-Up",
    "2nd Follow-Up",
    "3rd Follow-Up",
    "4th Follow-Up",
    "Escalation Flag",
]


class AgentState(TypedDict, total=False):
    invoice: InvoiceData
    days_overdue: int
    stage_key: StageKey
    stage_meta: StageMeta
    payment_link: str
    email_draft: Optional[EmailDraft]
    validation_status: Literal["approved", "rejected"]
    validation_feedback: str
    retry_count: int
    max_retries: int
    escalation_required: bool
    send_status: Literal["pending", "sent", "failed", "not_sent"]
    send_error: str
    audit_log: dict[str, Any]

model = ChatMistralAI(temperature=0.2)
email_agent = model.with_structured_output(EmailDraft)
EMAIL_GENERATION_CHAIN = EMAIL_PROMPT | email_agent

class MasterState(TypedDict, total=False):
    job_id : int
    csv_path: str
    raw_records: List[Dict[str, Any]]
    normalized_records: List[Dict[str, Any]]
    grouped_records: Dict[str, List[Dict[str, Any]]]
    batches: List[Dict[str, Any]]
    worker_results: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    errors: List[str]
    status: str