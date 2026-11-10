"""Vantage budget guard.

Triggered by Cloud Billing budget notifications on Pub/Sub.
  >= 50% of budget : switch live processing off (Firestore flag).
  >= 100% of budget: detach billing from this project (last resort).
Idempotent: safe to receive the same or repeated notifications.
"""
import base64
import json
import logging
import os
from datetime import datetime, timezone

import functions_framework
from google.cloud import billing_v1, firestore

PROJECT_ID = os.environ["PROJECT_ID"]
BUDGET_NAME = os.environ["BUDGET_NAME"]
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
SOFT_LIMIT = 0.5
HARD_LIMIT = 1.0

logging.basicConfig(level=logging.INFO)
db = firestore.Client(project=PROJECT_ID)


def _set_live_flag(enabled, reason, cost, budget):
    db.collection("config").document("demo").set(
        {
            "live_enabled": enabled,
            "reason": reason,
            "cost": cost,
            "budget": budget,
            "updated_at": datetime.now(timezone.utc),
        },
        merge=True,
    )


def _detach_billing():
    client = billing_v1.CloudBillingClient()
    client.update_project_billing_info(
        name=f"projects/{PROJECT_ID}",
        project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name=""),
    )


@functions_framework.cloud_event
def guard(cloud_event):
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    if payload.get("budgetDisplayName") != BUDGET_NAME:
        logging.info("Ignoring budget %s", payload.get("budgetDisplayName"))
        return

    cost = float(payload["costAmount"])
    budget = float(payload["budgetAmount"])
    ratio = cost / budget if budget else 0.0
    logging.info("cost=%s budget=%s ratio=%.2f dry_run=%s", cost, budget, ratio, DRY_RUN)

    if ratio >= SOFT_LIMIT:
        _set_live_flag(False, f"soft limit reached ({ratio:.0%} of budget)", cost, budget)
    if ratio >= HARD_LIMIT:
        if DRY_RUN:
            logging.warning("DRY RUN: would detach billing from %s", PROJECT_ID)
        else:
            _detach_billing()
            logging.warning("Billing detached from %s", PROJECT_ID)
