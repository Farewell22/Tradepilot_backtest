"""CLI for official policy document intake and human review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .store import PolicyStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="官方政策原文管理")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / "data/policy_news")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    importing = commands.add_parser("import-url")
    importing.add_argument("url")
    showing = commands.add_parser("show")
    showing.add_argument("document_id")
    candidate = commands.add_parser("adopt-candidate")
    candidate.add_argument("document_id")
    candidate.add_argument("sha_prefix")
    approving = commands.add_parser("approve")
    approving.add_argument("document_id")
    validating = commands.add_parser("validate")
    validating.add_argument("document_id")
    commands.add_parser("export")
    mapping = commands.add_parser("suggest-etfs")
    mapping.add_argument("theme_id")
    mapping.add_argument("event_at", help="首次公开日期或含时区时间")
    mapping.add_argument("--companies", type=Path, required=True)
    mapping.add_argument("--holdings", type=Path, required=True)
    mapping.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    store = PolicyStore(args.root)
    if args.command == "import-url":
        print(json.dumps(store.import_url(args.url), ensure_ascii=False, indent=2))
    elif args.command == "list":
        for folder in sorted((args.root / "documents").glob("*/draft.yaml")):
            print(folder.parent.name, store.status(folder.parent.name))
    elif args.command == "show":
        print((store.document_dir(args.document_id) / "draft.yaml").read_text(encoding="utf-8"))
    elif args.command == "approve":
        print(store.approve(args.document_id))
    elif args.command == "validate":
        _, _, events = store.validate(args.document_id)
        print(f"{len(events)} 条条款通过审核校验")
    elif args.command == "adopt-candidate":
        print(store.adopt_candidate(args.document_id, args.sha_prefix))
    elif args.command == "export":
        print(store.export())
    elif args.command == "suggest-etfs":
        import pandas as pd
        from .mapping import suggest_etfs
        result = suggest_etfs(args.theme_id, args.event_at,
                              pd.read_csv(args.companies, dtype=str, keep_default_na=False),
                              pd.read_csv(args.holdings, dtype=str, keep_default_na=False))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
