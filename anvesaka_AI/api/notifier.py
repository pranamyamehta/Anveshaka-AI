"""Slack webhook (primary) and optional email notification.

Owner: Member 4
Status: Done
"""
import logging
from typing import Any

import httpx

from anvesaka_AI.config import settings
from anvesaka_AI.schemas import TriageResult

logger = logging.getLogger(__name__)


def send_slack_notification(triage_result: TriageResult) -> bool:
    """Send a triage summary to Slack via webhook."""
    if not settings.slack_webhook_url:
        logger.debug("No Slack webhook configured. Skipping Slack notification.")
        return False
    
    color = "#FF0000" if triage_result.escalate else "#36A64F"
    text = (
        f"*Triage Result for {triage_result.alert_id}*\n"
        f"Decision: `{triage_result.decision.value}` | Priority: `{triage_result.priority.value}`\n"
        f"Root Cause: {triage_result.root_cause}\n"
    )
    if triage_result.recommended_steps:
        steps_text = "\n".join(f"- {step}" for step in triage_result.recommended_steps)
        text += f"\n*Recommended Steps:*\n{steps_text}"

    payload = {
        "attachments": [
            {
                "color": color,
                "text": text,
            }
        ]
    }
    
    try:
        response = httpx.post(settings.slack_webhook_url, json=payload, timeout=5.0)
        response.raise_for_status()
        logger.info("Successfully sent Slack notification for %s", triage_result.alert_id)
        return True
    except Exception as e:
        logger.error("Failed to send Slack notification for %s: %s", triage_result.alert_id, e)
        return False


def notify_triage_result(triage_result: TriageResult) -> list[str]:
    """Dispatch notifications based on configuration and return a list of successful channels."""
    sent_channels = []
    
    if send_slack_notification(triage_result):
        sent_channels.append("slack")
        
    # Email notification can be implemented here if a provider is configured
        
    return sent_channels
