import os
from dotenv import load_dotenv

load_dotenv()

def configure_tracing() -> None:
    if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        print("LangSmith tracing enabled.")
    else:
        print("LangSmith tracing disabled.")