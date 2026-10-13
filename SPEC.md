# Labels, company limits and a daily digest instead of stories

## What we're improving
Stories (one running thread per event) were built for Market One's wars and rate decisions.
On AI Flow they made no threads in three days and mostly re-filed what the duplicate check had
already caught, while getting it wrong both ways (held GPT-6.1 Sol Ultrafast, lumped two Managed
Agents launches together). The sorter also had one catch-all kind, "launch", for 23 of 29 posts.
nikita decided (2026-10-09): label every item with a kind and a company from fixed lists, retire
stories, widen the duplicate check to 7 days, and cap each company at 2 posts a day with the
rest going into one evening digest. Earlier specs are in docs/.

## Contract
GOAL:
- Every item that passes dedup gets a kind and a company from fixed lists, shown on the dashboard.
- A roundup ("DAILY AI BRIEF") is dropped and never posted.
- No story is placed, gated or threaded; a same-event repeat within 7 days is dropped.
- A company's 3rd+ post of the day (UTC) waits; at DIGEST_HOUR_UTC its waiting items go out as
  one bullet post (or a normal post if only one waits). A 5/5 item always posts.
- The dashboard has no Stories tab and shows kinds, companies, waiting items and the new graph;
  its guide and the README describe the new flow.

CONSTRAINTS:
- Labeler uses a cheap model (gemini-3.5-flash-lite), its own prompt in prompts/labeler.md.
- The dedup judge's prompt is not edited (tuned on hand-labelled pairs).
- Story code stays in the repo, switched off by config.STORIES, for a week; a copy goes to
  archive/market-one/ with notes. Same DB, new columns added by the existing migration list.

FORMAT: nodes/labeler.py, nodes/company_digest.py, prompts/labeler.md; stations and graph
wired by config; dashboard backend + frontend updated; README, SPEC, archive notes.

FAILURE (any of these = not done):
1. A label outside the fixed lists is stored (typo, new spelling, empty).
2. A roundup reaches the writer.
3. Any story station runs, or a post goes out as a reply, while STORIES is off.
4. A company gets a 3rd separate post in a UTC day from items scored below 5.
5. Waiting items are never posted or never expire (left waiting forever), or a digest posts twice in a day.
6. A same-event repeat 2-7 days after a published post is posted again.
7. The dashboard still shows a Stories tab / story stations, fails to build, or its guide describes stories.
8. Existing tests fail.

## Built on top of
- Existing machinery reused: sorter-style strict JSON schema (utils/openrouter.chat_json),
  the reserve's "waiting status" pattern, stories.as_source's folding + media.merge for the
  digest source, the writer's brief slot, the meta table for "digest done today".

## Gotchas we're handling
- A model can return a value off the list despite the schema: code maps it to "other".
- "other" kind no longer means irrelevant; relevance is the sorter's own yes/no.
- Old items keep their old kinds (launch/resource); reserve items labelled "resource" become "guide".
- Waiting items must not be swept by the 90-minute queue expiry (different status), and must
  expire after DIGEST_MAX_WAIT_HOURS so nothing waits forever.
- A digest is marked done before it runs, so a crash cannot send it twice.
- The writer's "roundup: pick one item" rule must not fire on our own digest: the brief overrides it.

## Build sequence
1. Spec + failing tests. 2. Labeler + sorter change. 3. Stories off + 7-day dedup.
4. Company limit + digest. 5. Dashboard. 6. Archive, README, guide. 7. Verify live.

## How to run and test
- `/usr/bin/python3 tests/test_ai_channel.py`, `/usr/bin/python3 tests/test_media.py`,
  `/usr/bin/python3 -m unittest tests/test_reader_memory.py`, `/usr/bin/python3 tests/test_labels_and_digest.py`
- `/usr/bin/python3 tools/check_labels.py` — the labeler against hand-checked labels
- `cd dashboard/frontend && npx tsc --noEmit && npm run build`

## Status
_Updated: 2026-10-09_
- All 7 steps done and live (aif-channel restarted 17:34 UTC; first items labelled correctly).
- Labeler (gemini-3.5-flash-lite): 60-61/61 on the tuned cases, 13/15 kinds and 15/15
  companies on 15 unseen ones. skills.sh items are forced to "skill" in code. Prompt fixes
  from the first run: hardware is always "other"; new_product only for listed companies,
  the same from anyone else is "tool"; a new thing inside any product is "feature".
- Stories are off by config.STORIES; their code stays until ~2026-10-16, then delete
  nodes/stories.py, nodes/coverage.py, the story stations/routes and STORY_* settings
  (copy and restore notes: archive/market-one/code/stories/).
- Route words in pipeline/stations.py are the graph's arrow labels; the channel saves
  LangGraph's diagram to meta.graph_mermaid at every start, and the dashboard draws it.
- With stories off the "place only" rounds are gone: a non-forced item that may not be
  sent this round is left queued (publish_loop), since nothing would stop it otherwise.
- Today's per-company counts start from the restart: items before it have no company.
- Pending (nikita asked to be reminded): tie the "try it" link search to the kind.

## Image resolution and publication evidence (2026-10-12)

GOAL: Reject images smaller than 800 pixels on the long edge or 400 on the short
edge before the analyst. Reject recycled commentary and sources without enough
information to write a useful post, across all sources. Retain genuine changes
and useful older skills/tools/guides without treating rediscovery as a launch.

CONSTRAINTS: Same sorter/model call; only two new answer fields: basis
(news/resource/none) and one supporting source quote. No release-date lookup,
new node, dependency, automatic edits to published messages, or sorter age rule
for resources. Keep existing audience, scoring, retry and human override rules.

FORMAT: Sorter rubric and schema, deterministic quote validation, rejection
reasons and accepted evidence visible in existing dashboard reason field;
source-independent regression cases and a real-model replay tool.

FAILURE: Missing/empty/invented quotes or basis=none can pass on a high score;
quotes from prompt labels or unseen truncated text pass; formatting normalization
changes a number; old explanations are treated as launches; genuinely useful
older resources are rejected solely for age or instruction-shaped skill content;
real launches/demos are rejected simply for being videos; schema reliability or
existing functionality regresses. Quote presence proves grounding, not meaning:
the semantic failures are checked on labelled examples, not guaranteed in code.

Built on top of: Existing OpenRouter strict JSON schema, standard-library Unicode,
HTML entity and whitespace normalization; no new dependencies.
[Schema reference](https://openrouter.ai/docs/guides/features/structured-outputs).
Pillow's decoded dimensions enforce image resolution; image rejection keeps text.

Build sequence: Tests before code; replay old sorter on labelled cases; add small
sorter change; verify code and real-model cases; replace AI/TLDR-only video filter;
update README/dashboard and activate after checks pass.

Run: `python3 -m unittest discover -s tests -p 'test_sorter_evidence.py'`;
`python3 tools/check_sorter.py --runs 2` (real API calls; isolated temporary DB);
image tests, article tests, channel/media/labels regressions and frontend type check.

Status: Complete. Image resolution remains active. Publication evidence now uses
only two additional fields in the same sorter call. Missing/invalid evidence and
basis=none reject in code; accepted basis and full quote persist in sorter_reason.
The AI/TLDR-only category filter is removed; collection freshness checks remain.
Tests: 12 evidence, 5 article, 6 image, 52 channel, 24 media, 11 labels/digest pass;
frontend production build and type/lint checks pass. Initial real-model run had
33/36 matches: one recycled announcement slipped through and generic business
instructions slipped through twice. Tightened the existing relevance section to
require a change-supporting quote and a specific AI use. Final 24 cases × 2 runs
matched 48/48 with no answer/model failures, including six unseen holdouts. DeepSeek
also rejected with a changed source/label and with video wording removed. Useful
older resources and real launches passed. This sample is not a guarantee of model
judgment on unseen articles; no independent release-date verification is claimed.
Reader-memory remains 27/28: the same pre-existing frozen-clock/SQLite-clock failure
reproduces on unchanged HEAD; stories are disabled. README and dashboard guide are
updated; the website guide ships with the next frontend deployment.
Activation: channel and dashboard API restarted on October 12; both
active, health endpoint returns 200, and the live graph shows the normal article
route and sorter evidence check. Published DeepSeek message is unchanged.

## Follow-ups that read as follow-ups, and a digest that cannot leak (2026-10-13)

What went wrong: Meta's Muse Wonder went out 3 times on 2026-10-12 (messages 64-66).
The dedup judge called a benchmark score of the launched model a "different event"; the
third item had a one-line feed text. repeat_check saw the earlier posts but let each through
for one new detail, and the writer was never told "these are the same product", so each
post re-introduced it. Separately, item 1048 was held by the Meta limit at 18:29 and the
18:00 digest released it two minutes later as a lone item: 3 Meta posts that day.

GOAL:
- Before writing, published posts about the same product/event (cosine >= FOLLOW_UP_SIMILARITY,
  0.70, source title + first 1500 chars vs post text, reader-memory window) reach the writer
  and the editor. The writer opens with what is new, does not re-introduce the product,
  repeat their facts, reuse their wording, opening or structure. Measured on 25 posts:
  same-product pairs 0.81-0.82, unrelated ones never above 0.64.
- A post sharing a 5-word phrase with a related post gets one rewrite request (code check).
- A company's digest takes only items that started waiting before today's DIGEST_HOUR_UTC.
  Items held after it wait for tomorrow's digest; expiry counts from when waiting began.
- Dashboard shows the digest post apart from the 2 regular posts ("2 of 2 + digest").

CONSTRAINTS: Reuse semantic_memory.published_matches, the writer's brief slot and the
editor's parent_post slot; no new model call except the one rewrite; dedup judge prompt untouched.

FAILURE: 1. A related post (>= 0.70) exists and the writer is not given it. 2. An unrelated
post (< 0.70) is given as related. 3. Reader memory down -> a post is written without the
check (it must wait, like repeat_check). 4. The editor rejects a back-reference to a related
post as invented (it must see those posts). 5. An item held after the digest hour is posted
that same day. 6. A waiting item expires before the digest it was waiting for. 7. Existing
tests fail. 8. UNVERIFIABLE in code: whether the wording reads natural - checked by replaying
items 1046 and 1048 through the real writer and showing nikita the before/after.

Run: `/usr/bin/python3 tests/test_follow_ups.py` plus the existing suites above.

Status: built and tested, NOT live yet (needs a restart of aif-channel and aif-dashboard-api;
the Companies page text ships with the next Vercel deploy). Tests: 10 follow-up, 52 channel,
24 media, 11 labels/digest pass; reader-memory still 27/28 (the known stories test); dashboard
builds. The old digest test now sets when waiting began (expiry counts from that).
Real-model replay of items 1046/1048 against the posts that existed then, 3 drafts each:
first try (follow-up note at the end of the system prompt) was ignored and one draft invented
"Muse Wonder Nano" (editor caught it) -> the note moved next to the source, gained "never fill
a thin update", and "best facts" was redefined as facts the reader lacks. After that: 4/6
lead with the new part without re-introducing the product, 0/6 copy a 5-word phrase, 3/6
approved by the editor on the first draft (the rest get the usual 3 rewrites). Still seen:
an old fact repeated in passing ("Full is for Muse Code subscribers"). Prompt-level, not a
guarantee; watch the next few follow-ups on the dashboard.

### The sifter: the writer only gets what is new (2026-10-13, nikita approved)
Why: asking the writer not to repeat old facts was not enough (replay above). Control its input.
GOAL: a new AI node `sifter` (nodes/sifter.py, prompts/sifter.md) between company_limit and
writer. It finds the related posts (follow_up.related_posts, moved out of the writer) and, if
there are any, lists the source's facts the reader does not have yet, each with a source quote.
Code keeps only quotes that appear in the source. The writer then gets ONLY those facts (no
source text, no source headline) plus the earlier posts. Nothing new -> item held, never written.
CONSTRAINTS: one cheap model call (SIFTER_MODEL, default the sorter's gemini-2.5-flash), only for
items with related posts. Editor still checks against the full source. Forced items get the
earlier posts but are never sifted or dropped (a human chose them); digests skip the sifter.
FAILURE: 1. The writer of a follow-up sees the source text or its headline. 2. A fact whose quote
is not in the source reaches the writer. 3. An item with nothing new is written or sent. 4. A
sifter outage drops an item (it must fall back to the earlier prompt-only follow-up). 5. Memory
down -> item written anyway. 6. Items with no related post change behaviour or cost a call.
7. Existing tests fail. 8. Checked by replay, not code: 1046/1048 drafts repeat no old fact.
Status (sifter): LIVE 2026-10-13 (aif-channel + aif-dashboard-api restarted; the dashboard
guide text ships with the next Vercel deploy). Tests: 18 follow-up/sifter, 52 channel, 24 media,
11 labels/digest pass; reader-memory 27/28 (known stories test); dashboard builds.
Real model: sifter consistent 8/8 on 1046/1048 (800 tokens ran out on 1048's long page -> 2500,
"at most 6 facts"); keeps only facts absent from the earlier posts; writer drafts from them
repeat no old fact. nikita chose (after a dry run turned 1048's leftovers - data centre, 14-month
overhaul - into a 4th post) that the sifter also judges worth_a_post: trivia -> held "not worth
a new post". Checked 12/12: 1046 after #64 and 1048 after #64-65 post; 1048 after all three and
the 1053 recap are held. Next: watch the first live follow-ups on the dashboard.

## More lab sources (2026-10-13, nikita approved)
Asked: Google, Microsoft, OpenAI's developer/Codex account on X, Z.ai, Kimi. Checked first:
AI Edge Foresight was posted (message 44, 2026-10-08); GLM-Legal arrived (item 1054) and the
sorter scored it 3/5 (gated beta for law firms). Jina Reader works (10 rescues since 10-07).
GOAL: feeds google_dev (developers.googleblog.com, undated) and google_ai (blog.google AI);
pages microsoft_ai (microsoft.ai/news, browser), kimi_blog (kimi.com/blog), zai_models
(docs.z.ai release notes -> each model's guide page); X @openaidevs, @googleaidevs, @microsoftai
(relay accounts.txt + config.X_ACCOUNTS, relay restarted). A feed's first successful read is
recorded, not queued (as pages already do), so an undated feed cannot flood the queue.
Jina Reader failures are logged as warnings (they were debug-only and invisible).
Not possible: Z.ai's blog has no index page and is not in its sitemap (nikita: pages only, no
@Zai_org); news.microsoft.com's AI feed is behind an intermittent Cloudflare challenge.
FAILURE: 1. A new feed's back catalogue is queued. 2. Existing feeds change behaviour. 3. A
page pattern takes navigation links (guides/overview, /blog itself). 4. config and the relay's
accounts.txt disagree. 5. tools/check_sources.py fails on a new source. 6. Existing tests fail.
Run: /usr/bin/python3 tests/test_new_sources.py; /usr/bin/python3 tools/check_sources.py
Status: LIVE 2026-10-13 00:50 UTC. Relay follows 9 accounts (rule confirmed by X); first reads
recorded 15 google_dev, 32 microsoft_ai, 9 kimi_blog, 8 zai_models, queued none (google_ai's 15
were all over 48h old). tools/check_sources.py: 11 working, 3 unchanged, 0 broken; it now works on
a temporary DB copy (it used to mark feeds as read in the live DB, which would have defeated the
first-read rule) and checks pages as pages (x.ai always showed as broken before). Tests: 6 new
sources, 18 follow-up, 52 channel, 24 media, 11 labels/digest pass; reader-memory 27/28 (known).

## Rumours, one product three times, a double send, source talk (2026-10-13 evening)
nikita woke up to: (1) the Adobe-clones post spoke of "the video claims" and had no link,
though the repos were public (github.com/storytold); (2) "Gemini's desktop app may be rolling
out custom tools" was a tracker's guess (so was #87, "Fable 5.5 traces spotted"); (3) Gemini 4
Argon posted 3 times in 31 minutes; (4) Apple TV 4K, entertainment; (5) the Facebook post twice.
CAUSES: (3) dedup returned at the first "same event" match, a rejected one-liner, and never met
the published post behind it; then the sifter found a true new fact each time; three more Argon
items waited for the 18:00 digest, which skips the sifter (held by hand at 17:48). (5) the clip
upload hit the library's 5-second wait, Telegram finished it anyway, and the code stepped down to
the picture, then text.
GOAL: sorter rejects news whose headline or quote hedges (sorter.UNCONFIRMED, news only; matched 2
of 332 past headlines, both rumours) and the rubric says so, plus gadgets/entertainment; dedup
looks past matches that never went out (dedup.COVERED); one post per product per
FOLLOW_UP_COOLDOWN_HOURS (12), checked before the sifter, which now runs BEFORE the company limit
so a repeat never waits for a digest; a Telegram timeout counts as sent (no step-down, no retry,
an alert), waits are 120 s; the writer never makes the source the subject and drops its author's
guesses, the editor's fixable SOURCE_TALK enforces it; AI/TLDR items with no product link get the
web link finder, which accepts an open-source project's GitHub page.
FAILURE: 1. A hedged news item passes the sorter. 2. A confirmed launch or a resource is blocked by
the word check. 3. A same-event repeat of a published item passes because a rejected one matched
first. 4. A second post about one product within 12 h, or in a digest. 5. A timed-out send goes out
again in any form. 6. A refused clip no longer falls back to the picture. 7. A post says "the
video"/"a report". 8. An aggregator item with no product link gets no search. 9. Existing tests fail.
Run: /usr/bin/python3 -m unittest tests/test_rumours_and_repeats.py (15);
python3 tools/check_sorter.py --runs 3; python3 tools/check_editor.py --runs 3
Status: LIVE 2026-10-13 17:49 UTC (both services restarted). Tests: 15 new, 52 channel, 24 media,
18 follow-up, 11 labels/digest, 6 sources pass; reader-memory 27/28 (known). Real models on 30
sorter cases x3: 88/90 (yesterday's rubric 77/90: posted Apple TV 3/3 and the DeepSeek explainer
2/3); 6 new cases from today's items. Editor 30 cases x3: 79/90 (yesterday's prompt 70/90, which
approved both source-talk posts 3/3); the misses are older cases whose "this week" went stale.
Trade-off nikita should know: the FIRST post about a product wins the 12 hours, so a tracker's
early "now in Agent Studio" can shut out the official launch post with prices an hour later.
