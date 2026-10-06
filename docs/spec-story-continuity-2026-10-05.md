# Story continuity and channel memory

## What we're improving
Market One repeated the US Treasury-yield climb on 2026-10-05 at 5.656%,
after reporting 5.5185% on September 25. Story 82 had closed; the placer also
missed live story 108 and opened 172. The final check scanned only 40 posts
within five days and asked about only the closest match. Earlier coverage
was invisible. This improvement applies to both channels, in their own databases.
The previous AI-channel spec is preserved in docs/spec-ai-channel-2026-10-04.md.

## Contract
GOAL: search every visible published post in a configurable time window,
default 60 days. Retrieve all posts above a permissive cosine floor (initially
0.60, calibrated on actual history), then let the editorial model judge them
together. The 5.5185% -> 5.656% example and the later mixed-maturity 5.7% /
24-year-high roundup must be held, even behind 40+ newer
posts or a closed story; reversals, new release periods and a first 6% yield
crossing must remain eligible. Similarity retrieves evidence; it never vetoes news.

CONSTRAINTS:
- Keep SQLite, NumPy, OpenRouter and the existing graph; no new paid service.
- Separate channel databases and existing writer/editor/sorter rules remain.
- Retain post and story history. Expire only cached embeddings after 60 days
  from publication (posts) or latest activity (stories); no automatic VACUUM.
- Existing authorization: nikita said "Proceed" after agreeing to broader
  semantic retrieval, story continuity and two-month embedding retention.

FORMAT:
- Persistent float32 embeddings with entity ID, model ID, dimensions and text
  fingerprint; reuse across checks/restarts and invalidate changed text/models.
- Date filter first, with no newest-N post cap. All shortlisted posts are read
  in bounded prompt batches; overflow is never silently omitted. A hold requires
  coverage, not merely one shared fact. A new fact beyond combined history sends.
- Story placement retains all live stories and also retrieves relevant recently
  closed stories within 60 days. Show IDs, names, original headlines and
  published evidence. A model-confirmed continuation reopens the existing story
  and preserves its posts/thread. Age alone does not create a new story.
- Reopened stories receive a fresh activity lifetime without changing first_at;
  old waiting items do not become fresh news just because a story reopens.
- A new story with relevant published history must face the story gate, rather
  than automatically publishing its first post. The exit check remains mandatory.
- Backfill tool caches the existing 60-day corpus without posting messages.
- Log candidate coverage, scores, model decisions, matched post/story IDs and
  unavailable checks. A repeat-check outage defers the draft for retry; it must
  not silently count as approval. Story-retrieval/placement outages also retry.
- Every send names literal new information and its kind. Exact decimal code
  validates claimed whole-percent crossings; a fractional reading, record date
  or another US Treasury maturity cannot earn send by itself. Invalid quoted
  approvals retry; a decision whose only grounds are disallowed refinements holds.

FAILURE (any of these = not done):
1. An eligible old post is hidden by a 30/40-post cap or only the closest match
   reaches the judge; prompt overflow silently drops candidates.
2. Either real Treasury repeat sends, an invalid/fractional threshold claim
   approves sending, or labelled reversals/new periods/whole-percent
   thresholds are held merely because the subject is similar.
3. An eligible closed/live Treasury story is hidden by expiry, a live-story cap,
   or loss of its published context; reopening loses history or closes next tick.
4. A new story skips the gate despite relevant channel history, or an unavailable
   repeat/placement check sends an unchecked post.
5. Cache reuse regenerates unchanged vectors, accepts a different model/text,
   mismatched/nonfinite/zero vectors or corrupt batch-index mapping.
6. Retention deletes text/send/story history, retains >60-day cache rows, includes
   deleted/rejected posts, or mixes channels. Existing item vectors are separate.
7. Migration/backfill cannot resume safely, rehearsals write to the live database,
   or the approved-post retry path bypasses the exit check.

## Built on top of
- Existing SQLite BLOBs and NumPy exact cosine scans; ~35 MiB for 6,000 vectors
  of 1,536 float32 values. No vector extension is needed at this scale.
- OpenRouter batch embeddings: https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings
- Cache/same-model guidance: https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag
- SQLite page reuse/compaction: https://www.sqlite.org/lang_vacuum.html
- Research: sqlite-vec is an alternative, currently pre-v1; adding an extension
  adds deployment/migration work without a demonstrated performance need.
- Exact decimal arithmetic: https://docs.python.org/3/library/decimal.html
- Typed judge output: https://openrouter.ai/docs/guides/features/structured-outputs

## Gotchas we're handling
- Cold start/model changes: resumable batch backfill and strict cache validation.
  Only the input and missing/changed snapshots call the embedding API.
- Many matches: bounded batches, followed by one combined coverage decision when
  multiple batches are required. Never send because an early batch says send.
- Publication age, not embedding creation/access time, drives retention. Freed
  SQLite pages are reusable; database file size need not immediately shrink.
- Reopening uses fresh activity age; scheduled releases still use their exact
  release key, so different periods are not accidentally merged.
- Every send must name quoted new information and its kind. Code checks whole-
  percent arithmetic; plain readings/record dates cannot become thresholds.
- Model outputs are validated. Temporary failures log and retry without opening
  a story or treating incomplete reader memory as a clean comparison.

## Build sequence
1. Regression tests first: temporary databases, no network, no channel messages.
2. Persistent cache, date-scoped queries, cleanup and resumable backfill.
3. Multi-candidate exit judging and the send-retry integration.
4. Live/closed story retrieval, reopening and gate evidence.
5. Existing checks plus real-history rehearsal; document and activate services.

## How to run and test
- Free tests: `CHANNEL=markets python3 -m unittest discover -s tests -p 'test_reader_memory.py'`
- Existing: `python3 tests/test_macro.py`, `python3 tests/test_media.py`,
  `CHANNEL=markets python3 tests/test_markets_unchanged.py`,
  `CHANNEL=ai_news python3 tests/test_ai_channel.py`.
- Backfill (cache only): `CHANNEL=markets python3 tools/check_reader_memory.py --backfill`
  and the same command with `CHANNEL=ai_news`.
- Private-copy rehearsals: `CHANNEL=markets python3 tools/check_reader_memory.py --incident`
  and `CHANNEL=markets python3 tools/check_reader_memory.py --labelled`.
- Mixed-yield regression: `CHANNEL=markets python3 tools/check_reader_memory.py --roundup`.
  `--model <id>` overrides only the rehearsal model.

## Status
_Updated: 2026-10-05, repeat incident at 18:54 UTC_
- Post 719 / message 597 repeated the Treasury
  climb after deployment. Retrieval worked (39 related posts including 588 and
  707); the story stayed in 172. Both gate and exit incorrectly called 5.7%
  a landmark. The exit reason contradicted its own whole-percent rule.
- The original tests covered 5.656% and genuine 6%, but missed a combined
  30-year 5.7% / 10-year 24-year-high roundup. Prior ALL PASS described that
  limited sample, not a reliable general safeguard.
- Built after failing regression tests: structured literal send grounds, decimal
  threshold validation, reading/record/related-US-maturity guards and audited
  accepted/refused grounds. Incomplete quoted approvals defer sending. Literal
  partial coverage is required only when combining multiple history batches.
- Validation: 28 memory tests pass for each channel; existing macro 2, prompt
  hashes 15, media 23 and AI 29 checks pass. Private-copy real-model rehearsals:
  original repeat held, matched live story 108, gate held; mixed 719 held with
  all 39 candidates in similarity/reversed/date order; real 6% crossing, falling
  yields and an added Fed decision sent. All 12 labelled cases pass.
- Keep the existing Mistral exit model. GPT-5-mini and Claude Haiku alternatives
  were trialled but not adopted; changing the model alone did not solve invalid
  arithmetic or evidence. Verification supplements the semantic model.
- Cache/retention/story retrieval remains active. General editorial judgments
  still depend on the model; these passing cases are regression evidence, not
  a guarantee that every future novelty judgment is correct.
- Activated: both channel services restarted at 22:15 UTC with the verified
  safeguard; both active. Private-copy rehearsals sent no channel messages.
