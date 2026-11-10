"""Central settings for the Vantage pipeline. Every value can be overridden by an
environment variable; the defaults describe the Vantage POC project."""
import os

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "vantage-poc-1110")

# Wall between projects: pin the quota/billing project for every Google client
# created by this code, regardless of what the machine-wide credentials say.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
os.environ.setdefault("GOOGLE_CLOUD_QUOTA_PROJECT", PROJECT_ID)

REGION = os.environ.get("GOOGLE_CLOUD_REGION", "europe-west2")

# Document AI: Enterprise Document OCR in the EU multi-region.
DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "eu")
DOCAI_PROCESSOR_ID = os.environ.get("DOCAI_PROCESSOR_ID", "9f864460e30c923")

INBOX_BUCKET = os.environ.get("VANTAGE_INBOX_BUCKET", "vantage-poc-1110-inbox")
TRUTH_BUCKET = os.environ.get("VANTAGE_TRUTH_BUCKET", "vantage-poc-1110-truth")
CLAIMS_PREFIX = "claims/"
OCR_PREFIX = "ocr/"

# Gemini 2.5 models retired on Vertex AI on 2026-10-20; keep the model a one-line change.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "global")
