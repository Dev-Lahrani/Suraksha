"""Command-line interface: python -m suraksha <command>."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suraksha", description="Suraksha early-warning assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create tables and seed districts")
    sub.add_parser("doctor", help="check local readiness without network calls or secrets")
    p_demo = sub.add_parser("demo", help="start labelled synthetic demo in a separate database")
    p_demo.add_argument("--port", type=int, default=8000)
    p_demo.add_argument("--host", default="127.0.0.1")

    p_ingest = sub.add_parser("ingest", help="run the ingestion + risk pipeline once")
    p_ingest.add_argument("--force", action="store_true", help="rebuild climatology too")

    p_run = sub.add_parser("run", help="start API server + hourly scheduler")
    p_run.add_argument("--host", default=None)
    p_run.add_argument("--port", type=int, default=None)

    p_ask = sub.add_parser("ask", help="ask the chat brain a question from the terminal")
    p_ask.add_argument("message", nargs="+")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.command == "demo":
        import os
        # Set before importing db: its engine is constructed at import time.
        os.environ["DEMO_MODE"] = "true"
        os.environ["DATABASE_URL"] = "sqlite:///data/demo.db"
        os.environ["INGEST_ON_STARTUP"] = "false"
        from suraksha.config import get_settings
        get_settings.cache_clear()
        import uvicorn
        uvicorn.run("suraksha.server.app:app", host=args.host, port=args.port, log_level="info")
        return 0

    if args.command == "doctor":
        from pathlib import Path
        from suraksha.config import get_settings
        from suraksha.db import District, SessionLocal, init_db
        init_db()
        settings = get_settings()
        with SessionLocal() as db:
            count = db.query(District).count()
        root = Path(__file__).resolve().parent
        assets = all((root / "web" / name).exists() for name in ("index.html", "app.js", "styles.css", "sw.js", "manifest.webmanifest"))
        checks = {"districts": count, "frontend_assets": assets, "demo_mode": settings.demo_mode,
                  "llm_optional_configured": bool(settings.nugen_api_key or settings.openai_api_key),
                  "whatsapp_optional_configured": bool(settings.whatsapp_token and settings.whatsapp_phone_number_id),
                  "signed_webhook_ready": bool(settings.whatsapp_app_secret),
                  "remote_admin_protected": bool(settings.admin_api_key),
                  "note": "Local readiness only; no provider/network verification. No secret values printed."}
        print(json.dumps(checks, indent=2))
        return 0 if count and assets else 1

    if args.command == "init-db":
        from suraksha.db import init_db

        init_db()
        print("✅ database initialised & districts seeded")
        return 0

    if args.command == "ingest":
        from suraksha.data.pipeline import run_pipeline
        from suraksha.db import init_db
        from suraksha.config import get_settings
        if get_settings().demo_mode:
            print("Live ingestion is disabled in demo mode", file=sys.stderr)
            return 1
        init_db()
        summary = asyncio.run(run_pipeline(force=args.force))
        print(json.dumps(summary, indent=2))
        return 0 if not summary["errors"] else 1

    if args.command == "run":
        import uvicorn

        from suraksha.config import get_settings

        # The scheduler is started inside the FastAPI lifespan (it needs a
        # running event loop); uvicorn owns the loop.
        s = get_settings()
        uvicorn.run(
            "suraksha.server.app:app",
            host=args.host or s.host,
            port=args.port or s.port,
            log_level="info",
        )
        return 0

    if args.command == "ask":
        from suraksha.agent.brain import handle_message
        from suraksha.db import init_db
        init_db()
        reply = asyncio.run(handle_message("cli", " ".join(args.message)))
        print(reply)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
