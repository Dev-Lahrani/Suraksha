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

    p_ingest = sub.add_parser("ingest", help="run the ingestion + risk pipeline once")
    p_ingest.add_argument("--force", action="store_true", help="rebuild climatology too")

    p_run = sub.add_parser("run", help="start API server + hourly scheduler")
    p_run.add_argument("--host", default=None)
    p_run.add_argument("--port", type=int, default=None)

    p_ask = sub.add_parser("ask", help="ask the chat brain a question from the terminal")
    p_ask.add_argument("message", nargs="+")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.command == "init-db":
        from suraksha.db import init_db

        init_db()
        print("✅ database initialised & districts seeded")
        return 0

    if args.command == "ingest":
        from suraksha.data.pipeline import run_pipeline

        summary = asyncio.run(run_pipeline(force=args.force))
        print(json.dumps(summary, indent=2))
        return 0 if not summary["errors"] else 1

    if args.command == "run":
        import uvicorn

        from suraksha.config import get_settings
        from suraksha.server.scheduler import start_scheduler

        s = get_settings()
        start_scheduler()
        uvicorn.run(
            "suraksha.server.app:app",
            host=args.host or s.host,
            port=args.port or s.port,
            log_level="info",
        )
        return 0

    if args.command == "ask":
        from suraksha.agent.brain import handle_message

        reply = asyncio.run(handle_message("cli", " ".join(args.message)))
        print(reply)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
