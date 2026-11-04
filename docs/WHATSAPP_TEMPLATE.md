# WhatsApp alert template (required for proactive alerts)

Meta only allows free-form messages within 24h of the user's last message. The
daily sweep therefore needs an approved **utility** template with ONE body variable.

Suggested body (category: Utility, language: English; add translations per language code):

    Suraksha climate alert: {{1}}

Submit it in WhatsApp Manager → Message templates, wait for approval, then set:

    WHATSAPP_ALERT_TEMPLATE=<template name>
    WHATSAPP_ALERT_TEMPLATE_LANG=en

Newlines in the variable are collapsed to spaces automatically. Verify with
`POST /api/alerts/sweep?dry_run=true` before enabling the scheduler in production.
Web Push (no template needed): `python -m suraksha vapid`, set the VAPID_* variables.
