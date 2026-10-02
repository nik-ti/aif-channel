# Market One — news channels that run themselves

One codebase, one channel per folder under `channels/`. The first is
**markets** (crypto / markets / geopolitics), live at @market_one_news.
`CHANNEL` in `.env` picks which one a process is.

**What it does:** reads news from RSS feeds and from X accounts, throws away
anything it has already covered or that isn't market-moving, rewrites what's left
into one consistent voice, has a second AI check the result, and posts it to your
Telegram channel.

**What starts it:** a systemd service running `main.py run`, which never stops.
Feeds are checked every 10 minutes; tweets arrive continuously.

---

## The flow

```
   RSS feeds  ──────┐
   (4 sources,      │
    every 10 min)   │
                    ├──►  fetch_rss.py   ─┐
                    │                     │
   X accounts  ─────┤                     ├──►  CHECK 1: same link?      (free, database)
   (via the shared  │                     │     CHECK 2: same headline?  (free, database)
    tweet relay,    ├──►  fetch_tweets.py ┘             │
    continuously)   │                                   ▼
                    │                        items table (status = queued)
                    └───────────────────────────────────┬───────────────────
                                                        │
              ┌─────────────────────────────────────────┘
              ▼
    ┌──  every 120 seconds  ─────────────────────────────────────────────┐
    │                                                                    │
    │   0.  drop anything that has gone stale (older than 90 min)        │
    │            │                                                       │
    │            ▼                                                       │
    │   1.  dedup.py      CHECK 3: same wording?   (rapidfuzz, ~1ms)      │
    │                     CHECK 4: same subject?   (embeddings — builds   │
    │                              a shortlist, decides nothing)          │
    │                     CHECK 5: same event?     (judge.py, ~50×/day)   │
    │            │                                                        │
    │            │        same TEXT  ──────────────────────────► dropped  │
    │            │        same EVENT ──► filed with that event's story    │
    │            │                       as fuel, no post of its own      │
    │            │        matched item in no live story ──► let through   │
    │            ▼                                                        │
    │   2.  sorter.py     AI · is it news? which market reprices?         │
    │            │        market impact 1-5 · "none" is capped at 3       │
    │            │        drops anything below MIN_IMPORTANCE (4)         │
    │            ▼                                                        │
    │   3.  article.py    read the linked page if the wire was thin       │
    │            ▼                                                        │
    │   4.  stories.py    which running story is this?                    │
    │            │        a SCHEDULED RELEASE is keyed by the calendar —  │
    │            │        no model, one release is one story              │
    │            │        anything else: AI picks, or opens a new one     │
    │            ▼                                                        │
    │   5.  stories.py    AI · has that story MOVED, or does a waiting    │
    │            │        item carry a fact the reader was never told?    │
    │            │        post / hold / this is not that story            │
    │            │        a hold ends here — the item waits as fuel       │
    │            ▼                                                        │
    │   6.  writer.py     AI rewrite of the WHOLE story into the voice    │
    │            │        deepseek-v3.2 · several wires become one post   │
    │            ▼                                                        │
    │   7.  editor.py     AI · approve or reject, naming a rule           │
    │            │        mistral-medium-3.1 · a different lab from the   │
    │            │        writer, and the one station that fails CLOSED   │
    │            ▼                                                        │
    │   8.  echo.py       AI · does the FINISHED POST tell the reader     │
    │            │        anything a post of the last 5 days did not?     │
    │            │        the last gate; nothing routes around it         │
    │            ▼                                                        │
    │   9.  image_analyst.py  AI · which picture, if any, goes with it?  │
    │            │        gemini-2.5-flash · "none" is a normal answer    │
    │            ▼                                                        │
    │  10.  video_analyst.py  AI · AI news channel only: does the clip   │
    │            │        show what the post says? over 2 min = no        │
    │            ▼                                                        │
    │  11.  publisher.py  send, with only the media chosen above         │
    │            │        max 2 per round, 4 per hour from .env          │
    │            ▼                                                        │
    │      YOUR TELEGRAM CHANNEL                                         │
    │            │                                                        │
    │            └─► every item the post did NOT actually mention goes    │
    │                back to waiting, checked in code by coverage.py      │
    └────────────────────────────────────────────────────────────────────┘
```

Roughly **$7.40 a month** at 40 posts a day, measured from the real prompts
and the real call volume. The sorter is 88% of it: a 4529-token rubric sent
142 times a day.

---

## Setup

**1. Settings and keys**

```bash
cp .env.example .env
nano .env
```

You need four things:

| Setting | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → /mybots → your bot → API Token |
| `CHANNEL_ID` | `@yourchannel`, or the `-100…` number from @userinfobot |
| `ERROR_CHAT_ID` | your own user id, from @userinfobot |
| `OPENROUTER_API_KEY` | openrouter.ai/keys |

The bot must be an **administrator** of the channel with **Post Messages** on.

**2. Check it**

```bash
python3 main.py check          # are the settings complete?
python3 main.py initdb         # create the database
python3 tools/check_sources.py # do all the feeds work?
```

**3. Rehearse before going live** — see the next section. Do not skip this.

**4. Install as a service**

```bash
sudo bash deploy/install-service.sh
```

Everything it needs is already installed on this machine. On a fresh one:
`python3 -m pip install --user --break-system-packages -r requirements.txt`

---

## ⚠️ Rehearse before going live

Posts go **straight to the live channel**. There is no approval button and no
preview channel. So `tools/test_brain.py` is your one chance to see what the AI
writes, and what the AI editor rejects, before either is doing it in public.

```bash
python3 main.py collect --once        # get some real news in
python3 tools/test_brain.py --limit 25 # run it through the brain, printed here
```

That costs about five cents and sends nothing. Read every post — is that the
voice you want? Then read every **rejection** especially carefully, and every
**📉 BELOW THE BAR** line: those are real stories the channel chose not to run,
shown with the market that would have had to reprice. That list is where you
find out whether the channel is about to be full of things nobody trades on, or
about to be silent.

This matters because of a real failure on this machine: a sibling project
(`systems/nmd_consulting`) has an editor node that quietly destroyed **110 of its
712 finished posts** — its reject list contained an ordinary common word. Nobody
noticed for months, because nothing recorded why. Everything in `nodes/editor.py`
is built to stop that happening here, but the rehearsal is still the step that
catches a badly-tuned prompt before your readers do.

Tune by editing `PROMPT` at the top of `nodes/writer.py` and `nodes/editor.py`,
then run the dry run again. Iteration is free and instant.

Once live, start cautious: put `MAX_POSTS_PER_HOUR=4` in `.env` and raise it
after a day or two.

---

## Nodes

### `fetch_rss.py`
- **What:** reads the RSS/Atom feeds listed in `config.SOURCES`.
- **In:** nothing · **Out:** `Article` objects
- **Why it's cheap:** it sends back the caching tokens each site gave it last
  time, so a site with no new articles replies "nothing changed" with no content
  at all. Most polls cost almost nothing.
- **Freshness gate:** articles older than `ARTICLE_MAX_AGE_HOURS` (24) are ignored.
  Blockworks is why — its feed still responds perfectly but its newest article is
  months old, and without this those would have been posted as today's news.
- **Watch out:** handles three feed formats (RSS 2.0, Atom, RSS 1.0/RDF). Getting
  that wrong fails *silently* — a valid page with no articles found in it. That
  happened with the DW feed on day one, so `check_sources.py` now reports any
  feed returning zero articles as broken.

### `fetch_tweets.py`
- **What:** reads X posts from the shared relay over Redis.
- **In:** nothing · **Out:** `Tweet` objects, with image addresses
- **Why a relay:** X allows one connection, and `trading/infra/tweet-relay`
  already holds it. It copies every tweet onto a shared conveyor belt; we watch
  it with our own bookmark (`news-channel` — the Redis group name, left as-is
  so the live stream does not lose its place), completely separate from the
  trading bot's (`sniper-ingest`). Both see everything; neither disturbs the other.
- **The important difference:** unlike the trading bot, we **catch up** after a
  restart rather than skipping what we missed — a news channel with a hole in it
  is a broken news channel. Three guards stop that flooding you: tweets older
  than 45 minutes are binned, at most 25 are kept per batch, and the hourly
  posting limit backs it all up. Tested: feeding all 95 tweets then on the belt
  through the filters produced **1** item.

### `dedup.py`
- **What:** decides whether we have already covered this story.
- **In:** an item · **Out:** dropped, filed with an event, or let through
- **The five checks,** cheapest first — see the table below.
- **A repeat is no longer destroyed.** The same TEXT — link, headline, wording or
  a near-identical vector — is still dropped, because nothing is lost. But when
  the judge rules "same event" on two items written DIFFERENTLY, the later one is
  filed with that event's story as fuel, with no post of its own. Different words
  carry different facts: "U.S. CORE PCE FALLS BELOW EVERY ANALYST FORECAST — below
  the entire range of 51 Bloomberg forecasts" was thrown away as a repeat of a
  thinner item about the same print, and so were two more accounts of it.
- **And "duplicate of item X" only counts when X was told to the reader.** If the
  matched item is in no live story, nothing has been published for this to repeat,
  so the item goes through untouched. That is the case that did the damage: three
  accounts of one inflation print were suppressed against an item whose post
  turned out to be about a Fed governor's speech instead.
- **Fails open:** if the meaning check or the judge is unavailable, the item is
  treated as new. A duplicate is a small embarrassment; a silent channel is worse.
- **It used to fail open in silence, which is a different thing.** A `dedup_hit`
  row is only written when two items MATCH, so "check 4 ran and found nothing"
  and "check 4 never ran and waved everything through" left identical evidence —
  none. Three tweets about one Fed decision went out four minutes apart and the
  database could not say which had happened. Now: failures are counted and
  logged, ten in a row sends you a Telegram alert, and **near misses are
  recorded** — a pair scoring just under the shortlist floor is written down as
  `kept=1`, so a floor set slightly too high is visible instead of invisible.
- **Diagnose it with `tools/check_dedup.py`.** It answers, in about a second:
  is the embedding service reachable; what share of processed items actually
  have a stored vector (if that is low, the check has been off and everything
  went out unchecked); which recent pairs were near misses; and
  `--pairs 30` scores what actually got published against itself, so you can see
  the exact score of any two posts that should have been one.

| # | Check | Cost | Catches |
|---|---|---|---|
| 1 | same link or tweet id | free | the same article re-listed every poll — most traffic |
| 2 | same headline | free | one story at two different addresses |
| 3 | same wording | ~1 ms | "Fed holds rates steady" vs "Fed leaves rates unchanged" |
| 4 | **same subject** | ~$0.000002 | draws up a **shortlist** of plausible repeats — the only check that can match a tweet to an article |
| 5 | **same event** | ~$0.00006 | **rules on that shortlist by actually reading both stories** — see `judge.py` |

#### Why check 4 is not allowed to decide on its own

It used to be, with one cutoff at 0.80, and it was wrong in **both directions at
once**. Measured on 20 hand-labelled pairs from this channel's own history:

```
real duplicates       scored 0.738 - 0.993
genuinely different   scored 0.785 - 0.900
```

Those ranges overlap, so no cutoff anywhere separates them. Two live failures:

- **Missed:** three posts about one Fed rate decision went out minutes apart
  (0.738, 0.745, 0.797 against a 0.80 line).
- **Wrongly merged:** *"$49.75M ETF **out**flows"* absorbed *"$32.11M ETF
  **in**flows"* at 0.900 — opposite events, a day apart. The second never posted.

Lowering the cutoff was measured too: at 0.72 it caught every real duplicate and
**doubled** the wrong merges. The cause is short text — with only a headline to
go on, the score tracks what a story is *about*, not what *happened*, and most
of what this channel reads is tweets.

Replaying a real day (188 items, 29 July) through the new ladder dropped 18
duplicates, **12 of which scored below the old 0.80 line** and would have been
posted twice.

#### The time gate

Before checks 4-5 run, candidates more than `DUPLICATE_MAX_GAP_HOURS` (12) away
are discarded outright. Recurring reports — daily ETF flows, weekly roundups —
are nearly word-for-word identical from one edition to the next, so yesterday's
is the single most dangerous thing in the pool. Every real duplicate measured
here arrived within 10.1 hours; the worst false merges were 24 hours apart.

#### The numbers guard

Checks 3 and 4 both refuse to merge two headlines differing only by a number,
because "Fed cuts 25bp" and "Fed cuts 50bp" score 97% alike and are completely
different events. It has already earned its keep: it rescued two different
weekly columns titled *New Ecommerce Tools: July 15* and *July 22*.

### `judge.py` (AI)
- **What:** given two stories that look alike, are they the same event?
- **In:** the new item + one candidate · **Out:** true/false + a written reason
- **Runs ~25 times a day** — only on the shortlist, not on everything.
- **Model:** `google/gemini-2.5-flash`. Measured 2026-09-30 on 40 real pairs from
  this channel's own `dedup_hits`: it agreed with the previous model on 39 of 40
  and answered all 40 in the required shape. A wrong merge silently deletes a real
  story; a missed duplicate just means one extra post. Prefer the model that errs
  towards publishing.
- **`deepseek-v3.2` was taken off this station.** Not for judgement — pinned to a
  provider that honours schemas it answered 40 of 40 — but because OpenRouter
  routes the same model id to thirteen providers and two of them return prose
  instead of JSON. Unpinned it answered 2 of 14. The station fails open, so those
  were silently treated as "not a duplicate".
- **`minimax-m2.7` is disqualified** here: 13 of 20 concurrent calls failed on
  rate limits and unreadable JSON. The judge fires in bursts by nature — breaking
  news arrives all at once.
- **Every verdict is logged** to `dedup_hits` with the reason in plain English,
  so you can see *why* a post vanished instead of guessing.

### `sorter.py` (AI)
- **What:** is this news at all, what topic, **which market has to reprice**, and
  how market-moving (1-5)?
- **The volume control.** Anything scoring below `MIN_IMPORTANCE` (4) is dropped.
  A ban that has *happened* is a 4; one being *considered* is a 3. Roughly 85% of
  general news is filtered out here.
- **This is the only node that asks "should we cover this?"** The editor
  downstream checks a finished post against its source — accuracy, hedging,
  format, safety — and its rule list contains nothing about a story being dull,
  deliberately. So when something uninteresting reaches the channel, this prompt
  is what needs changing, not the editor's.
- **It names the market before it scores.** The rubric used to ask only whether
  something had been "decided, enforced, or broken", which is an event test, and
  a war produces qualifying events daily. It let through *"Russian retailer
  evacuates warehouses after drone attacks"* — a real event, correctly filed as
  geopolitics, genuinely different from yesterday, and useless to anyone holding
  a position. The model now picks one of `crypto`, `rates_fx`, `energy`,
  `commodities`, `equities`, `risk_sentiment` or **`none`**, and `none` caps the
  score at 3 **in code**, not just in the prompt. A named transmission channel is
  a concrete claim you can disagree with later; "feels important" is not.
- **Two tests that stop a running conflict flooding the channel:** the
  *continuing-story* test (another instalment of something already underway is a
  3 unless it crosses a line — a new participant, a new class of target, a
  changed rule) and the *priced-in* test (a confirmation of what everyone
  expected is a 3).
- **Now inspectable.** Dropped stories get their own status (`low_impact`) rather
  than being mixed in with sport and opinion, and `tools/stats.py --dropped`
  prints them with the market and the reason. Same principle as the editor's
  audit log: a filter you cannot inspect is a filter you cannot fix.
- **Model:** `google/gemini-2.5-flash`, temperature 0.0. This is the one station
  where the model choice costs real money: it is sent the whole 4529-token rubric
  142 times a day, which is **88% of the channel's entire model bill** — $6.53 of
  $7.40 a month here, against $20 of $23 on claude-haiku-4.5. Prompt caching was
  measured and rejected: a cache read costs $0.000812 against $0.005091 uncached,
  but the cache expired after five minutes even when an hour was asked for, and
  the median gap between sorting rounds is 6.5 minutes. A miss costs $0.009909, so
  caching came out 21% dearer.
- **Why:** the main cost control. Rejecting a story here saves the writer's
  cost, which is seventeen times higher.
- **Fails soft:** if it breaks, we fall back to the source's own topic and carry
  on. It is an optimiser, not a safety gate.

### `stories.py` (AI) — the unit of work
- **What:** items do not become posts. They join a **story**, and a story posts
  when it has moved. Two questions, kept apart: `place()` asks which running
  story an item belongs to, `should_post()` asks whether that story has moved
  enough to be worth the reader's attention.
- **Why it exists:** on 1 September 2026 the channel posted fifteen times in four
  and a half hours about one war, and seven times about bond yields in a day.
  Every post was correct. The sequence read like a machine, because the thing
  that makes a channel read like a person — deciding NOT to post — had nowhere
  to happen. Replayed with stories, that day is 38 posts instead of 21, the war
  is 6 posts instead of 15, and the yields are 1 instead of 7.
- **Placement asks a model, not a number.** Measured on that day's wire, items
  inside ONE story scored 0.43-0.72 cosine against each other while unrelated
  ones reached 0.79. The ranges overlap, so no threshold can separate them. One
  call per item, shown every open story at once.
- **A story remembers itself as a sentence**, rewritten from each post as it goes
  out. That is what lets a story that opened with "two tankers hit in Hormuz"
  be recognised later as the war it became — and you can read it in the table.
- **A hold is never a drop.** `should_post()` always posts a story's FIRST post,
  so every story speaks at least once; a hold after that means "the reader
  already has this". Held items stay attached and feed the story's next post.
  Read the pile with `python3 tools/stats.py --held`.
- **The gate can undo a bad placement** by answering `not_this_story`. Without
  it, one misfiling silenced real news — that is how "Fed rate hike odds above
  66%" and "Russia cuts oil output" were lost in an early replay.
- **A scheduled release is not placed by a model at all.** The calendar named it
  before it happened, so every item about one release shares one story, keyed by
  country, title and scheduled time. Asking a model instead put the month's PCE
  inflation figure into a story about Fed officials giving speeches, and the post
  that came out was about the speeches.
- **The gate asks a second question now:** not only "has the story moved?" but
  "does a waiting item carry a fact the reader was never told?" Without it, an
  item filed by dedup would wait forever, because a better-worded account of the
  same event is not a change of state.
- **Placement fails open by leaving the item QUEUED, not by opening a new story.**
  A story with no posts always sends its first, so guessing here publishes
  duplicates — that is how one Treasury yield went out twice under two story
  numbers. The gate still fails open into posting. A run of ten failures alerts,
  because a dead model here reverts the channel to one post per item and nothing
  looks broken.

### `coverage.py`
- **What:** decides which of a story's waiting items a finished post actually
  covered.
- **In:** the post's text and the story's waiting items · **Out:** covered, or
  still waiting
- **No model is asked.** A model shown six items reports all six as used because
  it saw them. So an item counts as covered when the post repeats a detail that
  only THAT item supplied — distinctive measured against the story's other items,
  because inside one story every item shares the subject and "Trump" appearing in
  all of them proves nothing. An item that supplied nothing its siblings did not
  is covered by definition: there is no fact left to miss.
- **Why it exists:** every waiting item used to be marked covered the moment the
  story posted. Replayed over the channel's history, 9 of 42 had never been in the
  post that claimed them, including "US inflation remains at 3.4%", "Ethereum
  blasts to $2,800 for the first time since January" and "the cost of hiring an
  oil tanker has soared to $1 million a day".
- **The trigger item is always part of the comparison** even though it is never a
  candidate. Leaving it out buried an item about Trump rejecting a ceasefire,
  because the post's own source had made the word "Trump" look like that item's
  distinctive contribution.

### `echo.py` (AI) — the exit check
- **What:** the last question before a post is sent — has the reader already been
  told this?
- **In:** the finished post · **Out:** send, or hold
- **It stands at the exit, so nothing routes around it** — not a new story, not a
  roundup, not a forced post. And it compares the FINISHED POST against every post
  of the last 120 hours, which is the only comparison that matches what a reader
  sees.
- **It does not ask dedup's question.** A 30-year Treasury yield closing at 5.59%
  and touching 5.587% intraday are different events but the same news to a reader.
  Dedup ruled them different three times over and was right; the reader still got
  told twice in seven hours. This station asks whether the reader learns anything
  new, and its prompt spells out that a date is not a threshold — "highest since
  2002" after "highest since 2004" is one measurement still climbing.
- **Measured on 60 posts,** real repeats scored 0.741 to 0.924 and legitimate posts
  0.734 to 0.776, so the number only builds a shortlist and a model rules.
  Replaying the last 60 published posts: 11 pairs reach the shortlist, 6 hold, 5
  send.
- **It fails open,** and the cost of that is worth knowing: a model that cannot
  answer in JSON is indistinguishable from one that says send, and the log reads
  the same either way. That is not hypothetical — deepseek-v3.2 answered 7 of 8
  test pairs in prose and the check was dead for days while looking healthy. Run
  `tools/check_echo.py --labelled` before ever changing `ECHO_MODEL`.

### `writer.py` (AI)
- **What:** rewrites every story — articles and tweets alike — into one house
  voice, and picks at most one mark from `config.POST_MARKS` to lead with.
- **Tweets used to bypass this** via a mechanical `passthrough()`, because an
  early rewrite invented casualty figures during testing. That was safe but sent
  a third of the channel out in the source account's voice: sirens, ALL CAPS,
  cashtags. Since 28 Aug 2026 tweets go through the writer too.
- **What keeps the rewrite honest** is `LENGTH_RULE_BRIEF`, which applies to any
  thin source and forbids adding a single fact that is not in the source text,
  plus the editor checking the finished post against that source. The editor's
  `FACTUAL_DRIFT` rule explicitly covers background the model filled in from its
  own knowledge, even when that background is true.
- **The voice** comes from `channels/markets/persona.md`, prepended to the writer's prompt.
  That file is where you change how the channel sounds; the factual-accuracy
  rules in `nodes/writer.py` still override anything in it.

### `editor.py` (AI)
- **What:** the final check. Reads the finished post *against its source*.
- **Model:** `mistralai/mistral-medium-3.1`, temperature 0.0, with
  `minimax/minimax-m2.7` as the fallback. Both scored 7/7 on the 7 source/post
  pairs this station was calibrated on; they were swapped on 2026-09-30 for an
  operational reason only — minimax failed 28 times in one week, 16 of them by
  running out of room mid-answer, and the fallback finished every one of those
  calls. The work was already being done by mistral.
- **It must be shown the SAME source slice as the writer.** It read 1500 characters
  while the writer read 5000, and a story post's source is the story's items folded
  together — up to 4000. Anything the writer took past the cut looked invented. Of 74
  FACTUAL_DRIFT rejections on story posts, 29 had a source longer than 1500, and
  re-judging five of them with the whole source flipped two from rejected to approved.
  Both now read `config.MAX_BODY_CHARS`, so they cannot drift apart again.
- **Do not move this station without a test set containing KNOWN FALSEHOODS.** It
  fails closed and its job is catching lies, and the 7 pairs behind it were never
  saved. Testing on already-published posts only measures over-rejection:
  claude-haiku-4.5 approved 4 of 4 such posts where three other models declined
  one, which proves nothing either way. (It does now accept the strict schema —
  the older note here claiming it cannot was out of date.)
- **Deliberately a different model family from the writer** — a model judges its
  own writing badly, approving prose that sounds like its own habits.
- **Four safeguards against it becoming a black box:**
  1. It can only reject by naming a rule from a **fixed list of ten**. A
     rejection with no rule named is **treated as an approval** and logged. It
     cannot kill a post for a feeling.
  2. Every decision is recorded — approvals too — with the exact text judged.
  3. Rejecting more than half of the last 20 posts sends you a Telegram alert.
  4. `tools/stats.py --declines` prints rejections in full so you can judge them.
- **Fails closed:** no verdict means nothing is published; the post waits.
  (Note this is the *opposite* of dedup, on purpose.)
- **The gate sees the whole channel, not only its story.** It is shown the
  channel's recent posts that most resemble what came in, whichever story they
  were filed under. Stories close after 7 days, and the next post on a long
  run (yields, 1 October) used to be judged by a gate that had never seen the
  run's earlier posts.
- **Roundups are asked once.** When 3+ items have waited 3+ hours on a story
  that posted within the last 12, the gate is asked one more time whether
  together they tell the reader something new — and not again until another
  item joins. Before 1 October a roundup posted without asking, and the sweep
  re-asked every round until a "no" became a "yes".
- **Yields post once per whole percent** (5%, then 6%). A higher reading in
  between is the run continuing, unless something else happened: a sharp jump
  in a day, a central bank reacting, a failed auction. The exit check carries
  the same rule.

### `image_analyst.py` and `video_analyst.py` (AI) — the media
- **What:** choose the one picture, and on the AI news channel the one clip,
  that goes out with a post — or none. They never change or block the text.
- **In:** every candidate from every item the post was written from
  (`media.py`): all of a tweet's images, and on the AI channel the article
  page's pictures and video files · **Out:** the choice, with its reason, on
  the post row (`posts.media_*`)
- **The rubric is a text file:** `channels/<name>/image_rubric.md` and
  `channels/ai_news/video_rubric.md`. Rejected: a picture that just shows a
  person, stock photos and logos, another account's branding, anything
  unreadable on a phone, anything off the post's subject. Accepted only when
  it shows the data or is the maker's own announcement material.
- **It fails CLOSED:** if the check breaks, the post goes out on time with no
  media. The publisher sends only what is recorded on the post row, so a
  picture nobody judged cannot reach the channel.
- **Markets clips are not checked,** as before; their fallback picture is.
- **Two fixes the labelled set forced:** the model is told today's date (it
  read "highest since May 2025" as a date in the future), and it is told it is
  not fact-checking — it rejected a price chart on a market-cap post as "not
  market cap".
- **Measured** on 22 labelled images, 2 sets and 5 videos: 29 of 29, twice.
  About $0.0007 per picture and $0.003-0.004 per clip.
  Run `python3 tools/check_media.py --labelled` before changing a rubric or
  `IMAGE_MODEL` / `VIDEO_MODEL`; `python3 tests/test_media.py` checks the rules.

### `publisher.py`
- **What:** adds the one emoji and the source link, then sends.
- **One emoji per post, added by code and never by the AI:** `crypto → 🪙`,
  `geopolitics → 🌍`, and `⚡` in place of the topic emoji for short X posts.
  That single mark is the channel's whole visual signature.
  - The writer is told to use no emoji at all, and `strip_emojis()` removes any
    it produced anyway — for **every** post, not just the brief ones. Asking
    nicely in a prompt is not enough on its own.
  - It used to be allowed "1-3 that complement the content", which sounds
    reasonable and was not. Choosing an emoji is a judgement about tone, and the
    model made it badly on exactly the stories where tone matters: it put a 🔥
    on a drone strike.
  - Republished tweets are stripped too. These accounts write in sirens and
    rockets; the facts are reproduced exactly, only the decoration goes, so a
    tweet looks like everything else on the channel rather than announcing which
    account it came from.
- **No hashtags.** Dropped deliberately. Two tags covering the whole channel
  sorted posts the way this desk thinks rather than the way a reader does, and
  every post carried a line of tag that said almost nothing a reader couldn't
  already see. If they ever come back it should be per **market**
  (`#energy`, `#rates`) rather than per topic — that version would earn its line.
- **Pacing:** max 2 per round, 90 seconds minimum between posts, 12/hour, 60/day.
  Telegram would allow roughly 20 a *minute*; the limit here is about readers,
  not the API.
- **Images:** one message — photo with the text as its caption — never a photo
  then a separate message. If the text is too long to caption, the picture is
  dropped and the full text sent. If the image fails to send, it falls back to
  text. **A post is never lost over a picture.**
- **A post you delete in the channel leaves its story.** Telegram does not tell
  bots about deletions, so the publisher finds out when a reply to that post is
  refused. It marks the post `deleted`, which takes it out of every story query,
  and sends under the story's next surviving post, or as an ordinary post.
- **Injection defence:** any link in the post that doesn't point at our own
  source is stripped, keeping the words. This is plain code, not a model being
  asked nicely.

### `collect_loop.py`
- **What:** keeps the queue stocked. Two tasks at different speeds: feeds polled
  every `POLL_MINUTES`, tweets watched continuously — breaking news shows up on X
  first, and waiting ten minutes for it would waste the point of having the feed.
- **Deliberately does nothing else.** No AI, no writing, no sending. Its only job
  is turning "this exists out there" into "a row in our database", which is why a
  crash here can never produce a half-posted message.

### `publish_loop.py`
- **What:** drives steps 0-5 every 120 seconds.
- **Step 0 is not optional:** anything queued longer than 90 minutes is dropped.
  The posting limits mean intake exceeds output at busy times, so without expiry
  the queue grows forever and the channel ends up posting this morning's news at
  midnight. (A sibling project has 2,540 items stuck exactly like that.) Since
  the queue is ordered by importance, under pressure the best and freshest wins
  and the rest quietly dies — which is correct for news.

---

## Everyday use

```bash
python3 main.py stats               # how is it doing?
python3 tools/stats.py --declines   # what did the editor reject, and was it right?
python3 tools/stats.py --dropped    # what real news did the gate refuse to run?
python3 tools/check_sources.py      # are all the feeds still alive?
python3 tools/check_dedup.py        # is the meaning check actually running?
python3 tools/check_tweets.py       # watch the X stream live
tail -f logs/markets.log       # what is it doing right now?
```

### Adding a feed
Edit `SOURCES` in `config.py`, then `python3 tools/check_sources.py` to confirm
it works, then `sudo systemctl restart market-one-channel`.

### Removing a feed or an X account
Delete it from `SOURCES` or `X_ACCOUNTS`, then restart. The restart disables the
feed **and throws away everything already collected from it**.

That second half matters. Disabling a source only stops it being *polled* —
articles already sitting in the queue publish quite happily. A BBC article
reached the channel hours after that feed had been deleted, for exactly this
reason. `sync_sources()` now sweeps the queue on every startup, so removal takes
effect at once rather than eventually.

### Adding an X account
Two places, because the relay is shared with the trading bot:
1. `/home/nikita/trading/infra/tweet-relay/accounts.txt` — decides what X sends
   to the relay at all. Then `sudo systemctl restart tweet-relay`. This briefly
   interrupts the trading bot's tweet feed too; it reconnects by itself.
2. `X_ACCOUNTS` in `config.py` — decides which of those *this* channel wants.

### Changing the writing style
`PROMPT` at the top of `nodes/writer.py`. Rehearse with `tools/test_brain.py` before
restarting the service.

---

## Settings worth knowing about

| Setting | Default | What it does |
|---|---|---|
| `MIN_IMPORTANCE` | 4 | Only stories scored this high get published. **The main control on volume and triviality.** |
| `BRIEF_SOURCE_CHARS` | 400 | Sources shorter than this get the short-post treatment. X posts under it also get the ⚡. |
| `ARTICLE_MAX_AGE_HOURS` | 24 | Articles older than this are ignored — guards against an abandoned feed serving old content as news. |
| `X_MAX_AGE_MINUTES` | 45 | Same idea for tweets, and what stops a restart flooding the channel. |
| `MAX_POSTS_PER_HOUR` | 12 | Start at 4 while tuning, raise once happy. |
| `COSINE_SHORTLIST` | 0.72 | How alike two stories must look to be *considered* a repeat. This no longer decides anything — it only picks who gets read by the judge. Lower it if real duplicates are slipping past unexamined. |
| `COSINE_CERTAIN` | 0.95 | Above this, merge without paying for a judgement. Rarely fires (0 times in a 188-item day) — it only catches near-verbatim reposts. |
| `DUPLICATE_MAX_GAP_HOURS` | 12 | Two items further apart than this are never compared. **The cheapest accuracy setting in the project** — it is what stops yesterday's daily report absorbing today's. |
| `DEDUP_TOP_K` | 3 | How many shortlisted candidates get considered. Was effectively 1, which meant a rejected front-runner ended the search. |
| `JUDGE_MODEL` | `google/gemini-2.5-flash` | Decides "same event or not". Prefer a model that errs towards publishing. |
| `ECHO_MODEL` | `mistralai/mistral-medium-3.1` | The exit check. Run `tools/check_echo.py --labelled` before changing it — this station fails open, so a model that cannot answer looks exactly like one that says send. |
| `IMAGE_MODEL` / `VIDEO_MODEL` | `google/gemini-2.5-flash` | The media analysts. Run `tools/check_media.py --labelled` before changing either. |
| `MAX_VIDEO_SECONDS` / `MAX_VIDEO_MB` | `120` / `20` | Clips longer or bigger are refused in code, before any model call. |

## The four numbers worth watching

| Number | Where | What it means if it looks wrong |
|---|---|---|
| **Rejection rate** | `main.py stats` | Over ~33%, read the reasons — the editor is more likely too strict than the news that bad |
| **Share with market `none`** | `main.py stats` | Over ~90% means your sources are general news, not market news. Under ~40% means the model is inventing reasons to care — read `--dropped` |
| **Duplicates by check** | `main.py stats` | If check 4 never fires, your sources don't overlap or the threshold is too high |
| **Expired vs published** | `main.py stats` | More expiring than publishing means you collect more than you allow yourself to post |
| **Posts per day** | the channel | Does the pace feel right as a reader? |

---

## Troubleshooting

| Problem | Likely cause |
|---|---|
| Nothing is being posted | `main.py stats` — is anything queued? Is the editor rejecting everything? |
| "Chat not found" | `CHANNEL_ID` is wrong, or the bot was never added to the channel |
| "Not enough rights" | The bot is in the channel but isn't an admin with Post Messages |
| A feed stopped working | `tools/check_sources.py`. Sites move their feeds; you get an alert after 5 straight failures |
| No tweets ever arrive | `systemctl status tweet-relay`. Also check the handle is in **both** `accounts.txt` and `X_ACCOUNTS` |
| Duplicates getting through | **First run `tools/check_dedup.py`** — confirm checks 4-5 are running at all before touching anything. Then `stats.py`: if the pair never reached the judge, lower `COSINE_SHORTLIST` to just under the near-miss score reported. If the judge saw it and said "different", the prompt in `nodes/judge.py` needs the case adding. If `judge_error` is climbing, the model is unreachable and everything is failing open. |
| Real stories being merged | Look at the `judge` rows in `stats.py` — each records its reason in plain English. Fix the prompt in `nodes/judge.py`, not the floor; raising `COSINE_SHORTLIST` only hides the pair from the one thing that can judge it. |
| Posts sound wrong | Edit `channels/markets/persona.md`, rehearse with `test_brain.py` |
| Posts are real news but nobody would trade on them | `nodes/sorter.py`, not the editor. Check `stats.py --dropped --market none` to see what it *is* catching, then tighten the market definitions |
| The channel has gone quiet | `stats.py --dropped` — if good stories are in that list, the gate is too strict. Loosen the continuing-story test before touching `MIN_IMPORTANCE` |

---

## Layout

Shared machinery — none of it knows what a channel is about:

```
main.py            the orchestrator: run | collect | publish | initdb | check | stats
config.py          machinery settings, and it loads the active channel's profile
schema.sql         the database tables, the same for every channel
brain/             the graph: state, stations, routing
nodes/             one file per step of the pipeline (the diagram above)
                   coverage.py has no model: it checks in code which waiting
                   items a finished post actually mentioned
utils/             shared helpers: database, Telegram, OpenRouter, text cleaning
tools/             things you run by hand — none of them post anything
deploy/            the systemd units and log rotation
docs/              analysis and proposals, not code
```

What makes a channel itself — copy this folder to add one:

```
channels/markets/
   profile.py      sources, X accounts, thresholds, and its PIPELINE
   rubric.md       what this channel considers important (the sorter's prompt)
   persona.md      its voice
   nodes.py        optional: stations only this channel has
```

Per-channel files, named after the channel, in shared directories:

```
data/<name>.db     its database — never shared, dedup and stories read "everything recent"
logs/<name>.log    its log
.env               every channel's secrets, under its own keys (see profile.py)
```

The monitoring dashboard is a separate product that reads all of this:

```
dashboard/backend  read-only FastAPI over the database (systemd: m1-dashboard-api)
dashboard/frontend Next.js on Vercel
dashboard/SPEC.md  its contract
```

---

## Where this is going

Stories are built and live — see `nodes/stories.py`. Still open:

- **A way to tell whether a change helped.** Every tuning pass so far has been
  judged by eye, and the numbers wandered without anyone able to say which run
  was better. The instrument is a pairwise judge: same day, two pipelines, "which
  of these reads more like a person runs this channel".
- **Set the volume deliberately.** Roughly 20 posts a day now; the norm for a
  news channel is 3-5. That one number is what the story gate should be tuned
  against, and it has never been decided.
- **Thread a story's posts under its first one.** `publisher.execute()` already
  takes `reply_to_message_id`. A per-item guess at what was related fired on 66%
  of posts and was switched off; a story is a real thread, so this is safe now
  in a way it was not before.

- **Show the sorter's market judgement in the post**, so a reader can see why it
  was carried.
- **Wake the publisher on arrival** instead of the fixed `PUBLISH_TICK_SECONDS`
  sleep. That is the difference between a minute and ten seconds.
- **Style memory** — record what each post used (its mark, its opening, its
  shape) and pass the last few to the writer as constraints rather than as
  examples, so the channel stops repeating itself.
- **Log Telegram reactions**, so calibrating the importance gate stops being
  guesswork.
