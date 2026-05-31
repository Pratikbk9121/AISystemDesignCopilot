"""
Initialize Qdrant from local knowledge files.

Thin CLI around :func:`app.core.rag.bootstrap.bootstrap_knowledge`. Use this
when you want to seed (or reseed) the vector DB from a development machine.
The same function runs automatically in the FastAPI lifespan when
``AUTO_SEED_KNOWLEDGE=true``.

Examples
--------
    # idempotent seed from ./data/system_design_docs
    python scripts/initialize_qdrant.py

    # write sample docs if data dir is empty, then seed
    python scripts/initialize_qdrant.py --create-samples

    # ignore the up-to-date check and re-upsert everything
    python scripts/initialize_qdrant.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/initialize_qdrant.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.rag import QdrantVectorStore  # noqa: E402
from app.core.rag.bootstrap import (  # noqa: E402
    bootstrap_knowledge,
    create_sample_documents,
)


async def _run(data_dir: Path, force: bool) -> dict:
    vector_store = QdrantVectorStore()
    try:
        return await bootstrap_knowledge(
            vector_store, data_dir=data_dir, force=force
        )
    finally:
        vector_store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=str,
        default=settings.knowledge_data_dir,
        help="Directory containing knowledge files (.md/.txt/.json).",
    )
    parser.add_argument(
        "--create-samples",
        action="store_true",
        help="Write sample documents into the data dir if it is empty.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if the collection already has the expected count.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.create_samples:
        data_dir.mkdir(parents=True, exist_ok=True)
        if not any(data_dir.iterdir()):
            create_sample_documents(data_dir)

    # bootstrap_knowledge is async (vector_store.add_documents awaits the
    # embedding cache); wrap the entry point with asyncio.run for the CLI.
    result = asyncio.run(_run(data_dir, args.force))

    print(
        f"status={result['status']} loaded={result['loaded']} "
        f"skipped={result['skipped']} errors={len(result['errors'])}"
    )
    if result["errors"]:
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)
        return 1 if result["status"] == "error" else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
