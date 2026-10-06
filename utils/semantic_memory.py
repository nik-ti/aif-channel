"""Persistent reader memory shared by the story placer and the final repeat check.

Date-scoped records are searched exactly with NumPy. SQLite keeps reusable
vectors; the editorial model, rather than cosine, decides what is new.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import numpy as np

import config
from brain import persona_loader
from utils import db, embeddings, textclean, logger as log_setup

log = log_setup.get("memory")
BATCH_SIZE = 64


class Unavailable(RuntimeError):
    """Incomplete reader memory must be retried, never mistaken for new news."""


def prepared(text: str) -> str:
    return " ".join(textclean.for_embedding(text).split())[:2000] or " "


def _fingerprint(text: str) -> str:
    return hashlib.sha256(("reader-memory-v1\n" + prepared(text)).encode()).hexdigest()


def _vector(value, dimensions: int | None = None) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=np.float32)
        norm = np.linalg.norm(vector)
        if (vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all()
                or not np.isfinite(norm) or norm == 0
                or (dimensions is not None and vector.size != dimensions)):
            raise ValueError("invalid vector dimensions or values")
        return vector / norm
    except (TypeError, ValueError, OverflowError) as error:
        raise Unavailable(f"invalid memory embedding: {error}") from error


async def query_vector(text: str) -> np.ndarray:
    got = await embeddings.embed([prepared(text)])
    if not got or len(got) != 1:
        raise Unavailable("could not embed the proposed text")
    return _vector(got[0])


async def vectors_for(kind: str, rows: list[dict], *, dimensions: int | None = None,
                      persist: bool = True) -> list[np.ndarray]:
    """Backfill only missing/changed snapshots; completed batches survive restart."""
    cached = db.cached_memory(kind)
    result: dict[int, np.ndarray] = {}
    missing = []
    refreshed = []
    for row in rows:
        old = cached.get(row["id"])
        fingerprint = _fingerprint(row["text"])
        if old and old["model"] == config.EMBEDDING_MODEL and old["text_hash"] == fingerprint:
            try:
                vector = _vector(embeddings.from_blob(old["vector"]), dimensions)
                if vector.size != old["dimensions"]:
                    raise Unavailable("cached dimension metadata differs")
                dimensions = dimensions or vector.size
                result[row["id"]] = vector
                if persist and old["activity_at"] != row["activity_at"]:
                    refreshed.append((kind, row["id"], config.EMBEDDING_MODEL, fingerprint,
                                      vector.size, embeddings.to_blob(vector), row["activity_at"]))
                continue
            except (Unavailable, ValueError, TypeError):
                log.warning("Invalid cached %s %s — regenerating", kind, row["id"])
        missing.append(row)
    if refreshed:
        db.save_memory(refreshed)

    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start:start+BATCH_SIZE]
        got = await embeddings.embed([prepared(row["text"]) for row in batch])
        if got is None or len(got) != len(batch):
            raise Unavailable(f"incomplete {kind} memory: batch of {len(batch)} unavailable")
        vectors = []
        for value in got:
            vector = _vector(value, dimensions)
            dimensions = dimensions or vector.size
            vectors.append(vector)
        saves = []
        for row, vector in zip(batch, vectors):
            result[row["id"]] = vector
            saves.append((kind, row["id"], config.EMBEDDING_MODEL, _fingerprint(row["text"]),
                          vector.size, embeddings.to_blob(vector), row["activity_at"]))
        if persist:
            db.save_memory(saves)
        log.info("Cached %s memory: %d/%d missing snapshots", kind,
                 min(start+len(batch), len(missing)), len(missing))
    return [result[row["id"]] for row in rows]


def post_records(*, now: datetime | None = None) -> list[dict]:
    return [{**dict(row), "text": persona_loader.visible_text(row["post_html"]).strip(),
             "activity_at": row["sent_at"]}
            for row in db.memory_posts(config.ECHO_WINDOW_HOURS, now=now)
            if persona_loader.visible_text(row["post_html"]).strip()]


async def published_matches(text: str, *, now: datetime | None = None,
                            persist: bool = True) -> list[dict]:
    at = now or datetime.now(timezone.utc)
    rows = post_records(now=at)
    if not rows:
        log.info("Reader memory: no visible posts in %dh", config.ECHO_WINDOW_HOURS)
        return []
    query = await query_vector(text)
    vectors = await vectors_for("post", rows, dimensions=query.size, persist=persist)
    scores = np.stack(vectors) @ query
    matches = [{**row, "score": float(score)} for row, score in zip(rows, scores)
               if score >= config.ECHO_SHORTLIST]
    matches.sort(key=lambda row: (row["score"], row["sent_at"]), reverse=True)
    log.info("Reader memory: searched %d posts in %dh, %d above %.2f; best %.3f",
             len(rows), config.ECHO_WINDOW_HOURS, len(matches), config.ECHO_SHORTLIST,
             float(np.max(scores)))
    return matches


async def backfill(*, now: datetime | None = None) -> int:
    from nodes import stories
    at = now or datetime.now(timezone.utc)
    db.prune_memory_embeddings(now=at)
    rows = post_records(now=at)
    await vectors_for("post", rows)
    snapshots, _ = stories.memory_snapshots(at)
    await vectors_for("story", snapshots)
    return len(rows)
