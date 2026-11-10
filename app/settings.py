"""App settings. Pins the quota project so this repo never touches other projects."""
import os

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "vantage-poc-1110")
os.environ.setdefault("GOOGLE_CLOUD_QUOTA_PROJECT", PROJECT_ID)
REGION = os.environ.get("GOOGLE_CLOUD_REGION", "europe-west2")
INBOX_BUCKET = os.environ.get("INBOX_BUCKET", f"{PROJECT_ID}-inbox")
PAGES_PREFIX = "pages/"
