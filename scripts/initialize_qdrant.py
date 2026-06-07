"""
Initialize Qdrant from local knowledge files.

Thin CLI around :func:`app.core.rag.bootstrap.bootstrap_knowledge`. Use this
when you want to seed (or reseed) the vector DB from a development machine,
or to bake a persistent on-disk Qdrant index into a Docker image at build
time.

Docker build usage
------------------
At build time set ``QDRANT_USE_MEMORY=false`` and
``QDRANT_PATH=/app/data/vector_store/qdrant_data`` so the persistent
collection is materialised under the image layer (in-memory would vanish at
RUN-step exit). The script reads these via :mod:`app.core.config.settings`
which already binds them to env vars.

Examples
--------
    # idempotent seed from ./data/system_design_docs
    python scripts/initialize_qdrant.py

    # write sample docs if data dir is empty, then seed
    python scripts/initialize_qdrant.py --create-samples

    # ignore the up-to-date check and re-upsert everything
    python scripts/initialize_qdrant.py --force

    # wipe the collection then re-seed (used by Dockerfile so the baked
    # image always starts from a known clean state)
    python scripts/initialize_qdrant.py --clear
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


async def _run(data_dir: Path, force: bool, clear: bool) -> dict:
    """Construct the store, optionally wipe it, then bootstrap.

    The store is closed in a ``finally`` so the on-disk Qdrant file lock is
    always released — otherwise a subsequent Docker build step (or a
    follow-up `python scripts/initialize_qdrant.py` call) would fail with a
    "storage already accessed" error.
    """
    vector_store = QdrantVectorStore()
    try:
        if clear:
            # ``--clear`` re-creates the collection from scratch. Combined
            # with ``force=True`` below this guarantees a fully fresh index,
            # which is what we want when baking the image layer.
            vector_store.clear_collection()
        return await bootstrap_knowledge(
            vector_store,
            data_dir=data_dir,
            # When the caller asked for --clear, bypass the "already
            # up-to-date" fast-path so the empty collection actually gets
            # re-populated.
            force=force or clear,
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
    parser.add_argument(
        "--clear",
        action="store_true",
        help=(
            "Drop and recreate the collection before seeding. Used at Docker "
            "build time so the baked image always starts from a clean state."
        ),
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.create_samples:
        data_dir.mkdir(parents=True, exist_ok=True)
        if not any(data_dir.iterdir()):
            create_sample_documents(data_dir)

    # bootstrap_knowledge is async (vector_store.add_documents awaits the
    # embedding cache); wrap the entry point with asyncio.run for the CLI.
    result = asyncio.run(_run(data_dir, args.force, args.clear))

    # Print a final summary line that includes the post-seed points_count so
    # Docker build logs (and any CI consuming this stdout) make a regression
    # obvious. We re-open a tiny read-only client just for the count so the
    # main path's finally-close already released the file lock.
    final_points = None
    try:
        check_store = QdrantVectorStore()
        try:
            final_points = int(
                check_store.get_collection_info().get("points_count") or 0
            )
        finally:
            check_store.close()
    except Exception as e:  # noqa: BLE001 — diagnostic only.
        print(f"warning: could not read post-seed points_count: {e}", file=sys.stderr)

    print(
        f"status={result['status']} loaded={result['loaded']} "
        f"skipped={result['skipped']} errors={len(result['errors'])} "
        f"points_count={final_points}"
    )
    if result["errors"]:
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)
        return 1 if result["status"] == "error" else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
