// The full pipeline explanation shown under the Graph tab's Mermaid diagram.
// Written by Claude Haiku (the session owner) as A-to-Z context for how the
// system works. Kept verbatim — this is content, not something to summarize.
export const WORKFLOW_EXPLANATION = `
# Market One News Channel — Complete Workflow (A to Z)

## 🔄 The Complete Pipeline

### Phase 1: COLLECTION & DEDUPLICATION
News arrives from multiple sources:
- RSS feeds (BullTheoryio, Barchart, etc.)
- Twitter/X posts (via tweet-relay service)
- Reuters, Bloomberg, and other wire services

**Deduplication — five checks, cheapest first.** An item only reaches a check if
everything above let it through. Embeddings alone never decide; an LLM does.

1. **Same link or tweet** — free, enforced by the database.
2. **Same headline** — free, a fingerprint of the headline text.
3. **Nearly the same wording** — ~1ms, rapidfuzz ratio ≥ 92 within 24h.
   "Fed holds rates" vs "Fed leaves rates". If the two differ *only by a number*
   ("16 dead" → "17 dead"), it is **kept**, not merged — scoring cannot tell that
   apart from "Fed cuts 25bp" → "50bp", and both score ~97%.
4. **Same subject** — one embeddings call. This produces a **shortlist, not a
   verdict**:
   - **≥ 0.95** — near-verbatim, merged without paying for a judgement
   - **≥ 0.72** — worth asking about, goes to check 5 (top 3 candidates, 48h window)
   - **below 0.72** — a different story, stop here
5. **Same event** — one LLM call. The judge reads *both* texts and rules three ways:
   duplicate, different, or **continuation**. A continuation is not a duplicate and
   is not dropped — where it belongs is the story layer's question, and it has every
   open story to go on rather than one pair.

*Why check 5 exists:* on 19 hand-labelled pairs from this channel, real duplicates
scored 0.738–0.993 and genuinely different ones 0.785–0.900. **The ranges overlap**,
so no single cosine cutoff can work. The embedding tracks what a story is *about*;
only the judge reads what actually *happened*.

*A time gate runs before checks 4 and 5:* candidates far apart in time are discarded
first. Daily ETF flows are near-identical edition to edition, so yesterday's is the
most dangerous thing in the pool. Every real duplicate measured here arrived within
10.1 hours; the worst false merges were 24 hours apart.

*It fails open:* if the embeddings or the judge are unavailable, the item goes through
unchecked. A duplicate is a small embarrassment; a silent channel is worse. Every such
failure is counted, and a run of them raises an alert.

**A repeat is no longer destroyed.** The same *text* — link, headline, wording, or a
near-identical vector — is still dropped, because nothing is lost. But when the judge
rules "same event" on two items written **differently**, the later one is filed with
that event's story as fuel and gets no post of its own. Different words carry
different facts: on 30 September "U.S. CORE PCE FALLS BELOW EVERY ANALYST FORECAST —
below the entire range of 51 Bloomberg forecasts" was thrown away as a repeat of a
thinner item about the same print, and so were two further accounts of it.

**And "duplicate of item X" only counts when X reached the reader.** If the matched
item is in no live story, nothing has been published for this to repeat, so the item
goes through untouched. That is the mistake that did the real damage: three accounts
of one inflation print were suppressed against an item whose post turned out to be
about a Fed governor's speech.

---

### Phase 2: SORTING & FILTERING (Sorter Node)
The sorter judges: "Is this worth posting?"

It returns four fields: **relevant** (true/false), **topic** (\`crypto\`,
\`geopolitics\` or \`other\`), **market** — which market has to reprice — and
**importance, 1 to 5**. The bar to publish is **4**.

**The question it actually asks is "who has to look again?"** Not "is this
interesting". An item scores on *how much of the world reprices*:

- **US data — CPI, payrolls, the Fed** — reprices everything: a **5 or 4**.
- **Eurozone, China, Japan** headline releases reprice a large region: a **4**.
- **Any other single economy's** inflation, jobs, GDP or rate decision reprices its
  own currency and little else: a **3**, *even when the number surprises*. Canada's
  inflation is a 3. Australia's rate decision is a 3.

**The market field is a hard gate, enforced in code, not just asked for.** If the
model answers that **no** market has to reprice, the item is capped at **3** —
deliberately one below the bar. A model that says nothing needs repricing and then
scores the item 4 has contradicted itself, and the concrete field is believed over
the number. This is why most items die here with \`market none\`.

**It also holds the economic calendar:** the sorter is shown the scheduled release
this item matches, with its forecast and previous value, so it can tell a number that
landed on consensus (already priced in) from one that did not.

**Output:** relevant → continues; otherwise \`low_impact\` or \`irrelevant\`, archived
with a written reason you can read on the Posts tab.

---

### Phase 3: STORY PLACEMENT (Place_Story Node)
News doesn't post as isolated items. Instead, it joins a **story** — a grouping of related developments.

**How placement works:**
1. **If the item is about a scheduled release, no model is asked at all.** The
   calendar named that release before it happened, so every item about it shares one
   story, keyed by country, title and scheduled time. Asking a model instead put the
   month's PCE inflation figure into a story about Fed officials giving speeches, and
   the post that came out was about the speeches.
2. Otherwise: look at all currently open stories
3. Use an LLM to decide: "Does this item belong to story #82 (Treasury yields), or is it new?"
4. Output: either attach to an existing story OR create a new one

**When the model cannot be reached, the item stays queued** and is asked again in two
minutes. It is *not* opened as a new story: a story with no posts always sends its
first, so guessing here publishes duplicates — that is how one Treasury yield went out
twice under two story numbers.

**Story definition:**
- A story is a single ongoing event or theme
- Example: "Treasury yields rising across the curve" (story ID 82)
  - Item 1: "2-year yield hits 4.794%"
  - Item 2: "30-year yield reaches 5.367%"
  - Item 3: "10-year note hits 5.081%"
  - These are 3 separate news items but ONE story

*Why:* Without this, the channel posts 15 updates about one war, or 7 about bond yields, overwhelming readers. Stories keep related news grouped.

---

### Phase 4: STORY GATE (Should_Post Node)
The gate asks two questions: "Has the story state changed?" and, if not, "does a
waiting item carry a fact the reader was never told?" The second one matters because
dedup now files other accounts of the same event here, and a better-worded account is
not a change of state — without the second question those would wait forever.

**There is no single ladder.** Each kind of situation has its own short list of
states, and only a move between them earns a post:

| situation | its states |
|---|---|
| a war | not started → fighting → ceasefire → fighting again → widened → over |
| a dispute | talks → tariffs imposed → deal |
| a case | filed → ruled → appealed |
| a price run | below a landmark → through it (once) |

**It HAS changed state when:** a ceasefire, truce, deal, ruling or resumption puts
the situation somewhere else than the last post described; a **new** party or front
enters (a second country's ships are hit, a second regulator opens a case); or a price
crosses a landmark the reader will remember — a record, a multi-year extreme, a major
round number — for the **first** time in this story. **For yields the only landmark is a
whole percent** (5%, then 6%): 5.23% → 5.30% → 5.9% is the same climb, and so is the
10-year doing what the 30-year already did. Only a sharp jump within one day, a central
bank reacting or a failed auction makes a yield newsworthy in between.

**It has NOT changed state when:** another incident happens inside the same state
(another strike, another tanker, more casualties — the war was on before and is on
now); another piece of the same squeeze is disrupted; or a different outlet reports
what the reader was already told, *including* a fuller write-up of it.

**Gate logic:**
- **First post of a story:** always posts. Every story speaks at least once, so a
  "hold" always means "the reader already knows about this", never "this was never covered".
- **Second post onward:** only on a state change, by the test above.
- **Held items:** kept, and carried by the story's next post or by a roundup.
- **The gate sees the whole channel, not only its story.** It is shown the channel's
  recent posts that most resemble what came in, whichever story they were filed under.
  Stories close after 7 days, and on 1 October a long yields run was judged by a gate
  that had never seen the run's earlier posts.

**Roundups.** When **3+ items** have been held on a story for **3+ hours** since its last
post (and that post was under **12 hours** ago), the gate is asked **once** whether,
taken together, they tell the reader something new. If yes, the writer gets only those
new facts as an "update" with bullets; if no, nothing is asked again until another item
joins the story. Until 1 October a roundup was released by arithmetic alone, with no
model asking "is this new?" — that is how a diesel update went out repeating two earlier
posts — and the sweep re-asked every round until a "hold" became a "post".

*Note:* the **State** shown on the Stories tab is not one of these — it is the story's
own lifecycle, \`live\` or \`closed\`. The states above live inside the gate's judgement,
not in the database.

---

### Phase 5: WRITING (Writer Node)
For items that pass the gate, the writer composes the Telegram post.

**Writer rules:**
- **Headline:** One fact = one line (no fluff)
- **Body:** Answers questions the headline leaves open, sourced only from the wire (never invented)
- **Length:** Tight (often just headline, sometimes 2-3 lines of detail)
- **Emoji:** one mark at the start, from a fixed list in \`config.py\` (\`POST_MARKS\`) plus country flags —
  e.g. 🔺/🔻 a number moving, 🏛️ a central bank, 🛢️ oil, 💱 forex, 🏠 housing, 🔬 research,
  💎 diamonds and gems (not gold or silver), 🫆 fingerprints and biometrics. Anything off the list is deleted by code.
- **Bullets:** Use ▪️ whenever a list fits
- **Scheduled releases (📍, set by code):** the figure, the forecast and the previous value on separate lines,
  then one short paragraph — what the indicator is, and whether it beat the forecast, read by a fixed table
  (inflation above forecast = negative, growth above = positive, and so on). The source's own consensus
  beats the calendar's when it gives one, because the calendar match is sometimes wrong.

  \`\`\`
  📍 US PPI m/m: +0.4%
  Forecast: +0.2%
  Previous: +0.1%

  PPI tracks the prices producers charge, an early read on inflation. It came in above
  the forecast, which is a negative sign for the markets.
  \`\`\`

---

### Phase 6: EDITING (Editor Node)
The editor validates the post before sending.

**It can only reject by naming one of 11 rules** — the list is enforced by the
schema, so it cannot invent a reason:

\`FACTUAL_DRIFT\` · \`OVERCLAIM\` · \`HYPE\` · \`NO_NEWS\` · \`WRONG_TOPIC\` ·
\`EMPTY_BODY\` · \`INCOMPLETE\` · \`TOO_LONG\` · \`BROKEN_HTML\` · \`INJECTION\` · \`UNSAFE\`

The rule that fired is written into the item's reason, which is what you read on the
Posts tab — e.g. \`editor rejected it ['WRONG_TOPIC']: ...\`.

**Some rules are fixable, some are fatal.** A fixable one (a broken tag, an empty
body) sends the post back to the writer for another attempt, up to a limit. The rest
end it.

**This is the one station that fails CLOSED.** Everywhere else — dedup, the sorter,
placement, the gate — a failure lets the item through, because a silent channel is
worse than a duplicate. Here the reasoning inverts: if the editor cannot judge the
text, nothing is sent. A wrong post cannot be recalled.

---

### Phase 7: THE EXIT CHECK (Repeat_Check Node)
The last question before anything is sent: **has the reader already been told this?**

It stands at the exit, so nothing can route around it — not a new story, not a roundup,
not a post you forced from this dashboard. And it compares the **finished post** against
every post of the last 120 hours, which is the only comparison that matches what a
reader actually sees. Every other guard compares wire items, and a reader never reads
wire items.

**It deliberately does not ask dedup's question.** A 30-year Treasury yield closing at
5.59% and touching 5.587% intraday are different events — dedup ruled them different
three times over and was right — but they are the same news to a reader, who got told
twice in seven hours. This station asks whether the reader *learns* anything, and its
prompt spells out that a date is not a threshold: "highest since 2002" after "highest
since 2004" is one measurement still climbing. A round number crossed for the first
time is a threshold; a year is not. For a yield only a **whole percent** counts — 5.3%
is a new reading, not a threshold — and the 10-year repeating the 30-year's move is not
a new actor.

Measured on 60 posts, real repeats scored 0.741–0.924 and legitimate posts 0.734–0.776,
so the number only builds a shortlist and a model rules.

*It fails open,* and the cost of that is worth knowing: a model that cannot answer in
JSON is indistinguishable from one that says send, and the log reads the same either
way. That is not hypothetical — one model answered 7 of 8 test pairs in prose and this
check was dead for days while looking healthy.

---

### Phase 7½: THE MEDIA ANALYSTS (Image_Analyst and Video_Analyst Nodes)
Which picture goes with the post — and on the AI news channel, which clip — or none.
They never change or block the text; they only choose the media.

**Candidates** come from every item the post was written from: all of a tweet's
images (not only the first, as before), and on the AI channel the article page's
pictures and video files too.

**The image rubric** (\`channels/<name>/image_rubric.md\`, editable without code):
- **Rejected:** a picture that just shows a person · stock photos and logos · another
  news account's branding, watermark or "BREAKING" template (a chart platform's small
  logo is fine) · unreadable on a phone · a different subject from the post.
- **Accepted only** when it shows the data (a chart of the move, a table of the
  release) or is the maker's own announcement material.
- Several pass → the single best one. **None passing is normal**, not an error.

**The video analyst** (AI news only): a clip over **2 minutes** or **20 MB** is refused
in code before any model sees it; the rest go to Gemini, which asks whether the clip
shows what the post says. A passing clip beats a picture; the picture is its fallback.
On Market One, clips go out unchecked as before — only their fallback picture is judged.

**It fails closed.** If a check breaks, the post goes out on time with no media. The
publisher sends only what is recorded on the post row, so nothing unjudged gets out.
Measured on 29 labelled cases: 29 of 29, twice. About $0.0007 a picture.

---

### Phase 8: PUBLISHING (Publish Node)
Approved post is sent to Telegram \`@market_one_news\`

**Rules:**
- **Channel-wide: 4 posts an hour** (\`.env\` overrides the \`config.py\` default of 12).
  When that ceiling is hit, items are still sorted and placed into stories — only the
  sending waits. Otherwise a busy hour would expire the queue and lose the content.
- **Per story: a 6-minute minimum gap and 12 posts maximum.** Both are context for the
  gate rather than hard walls — a 25-minute gap once silenced a real escalation.
- A later post in a story **replies to that story's first post**, so it reads as a thread.
- **A post you delete in the channel leaves its story.** Telegram does not tell bots
  about deletions, so the publisher finds out when a reply to that post is refused. It
  marks the post \`deleted\` — out of the story, out of what the gate and the exit check
  remember — and sends under the story's next surviving post, or as an ordinary post.
- Video and GIFs from a tweet are sent as real media, not a link — except from
  \`crypto_banter\`, whose media is dropped on purpose.
- An item that waits in the queue longer than **90 minutes expires**. Late breaking news
  is worse than none. Items *held* on a story are exempt — they are waiting on purpose.

**After the send, only the items the post actually mentioned are marked covered.** This
is checked in code with no model: an item counts as covered when the post repeats a
detail that only *that* item supplied. A model shown six items reports all six as used
simply because it saw them, so it is not asked.

*Why this exists:* every waiting item used to be marked covered the moment the story
posted. Replayed over the channel's history, **9 of 42 had never been in the post that
claimed them** — including "US inflation remains at 3.4%", "Ethereum blasts to $2,800
for the first time since January", and "the cost of hiring an oil tanker has soared to
$1 million a day". Each carried a note saying the reader had been told. Anything the
post did not carry now goes back to waiting, for that story's next post.

---

## 🎯 Dashboard Summary

The dashboard shows you **this entire pipeline in real time:**

| Stage | Shows | Status Colors |
|-------|-------|---|
| **Collection** | Raw items arriving | All incoming news |
| **Dedup** | Caught duplicates | 🔵 duplicate |
| **Sorter** | What passed/failed filters | 🟢 passed, 🔴 low_impact/irrelevant |
| **Stories** | Grouped items, state machine | All open stories + their items |
| **Gate** | What posts vs. holds | 🟢 published, 🟡 held, 🔴 rejected |
| **Writer** | Composed post text | Full text + metadata |
| **Editor** | Validation results | ✓ approved, ✗ rejected (reason shown) |
| **Exit check** | Posts held for repeating a recent one | 🟡 held |
| **Publish** | Sent to Telegram | Timestamp + message ID + a link to the post |

A published item's **Why** field shows the editor's own reason for approving it, not
"sent as message 530", and every sent post carries a **View in Telegram** button.

---

## 💡 Key Concepts to Remember

1. **One item ≠ one post.** An item is a news wire. A post is what readers see. 3 wire items → 1 post if they're the same story state.

2. **Embeddings shortlist, an LLM decides.** Cosine similarity says what two items are *about*; it cannot say whether the same thing *happened*. Real duplicates and genuinely different stories overlap on that score, so anything between 0.72 and 0.95 is handed to a judge that reads both texts.

3. **A story speaks once per state, not once per wire item.** "Yields through a multi-year high" posts once; the next yield print inside the same move is held. A ceasefire, a ruling, a new party entering, or a price through a landmark it has not crossed before starts the next post.

4. **Gate = second opinion.** If the sorter misplaces an item, the gate can eject it to its own story, preventing silent loss.

5. **Dedup files, it does not delete.** The same *text* is dropped. The same *event*
told in different words is filed with that event's story, because different words carry
different facts. And "duplicate of item X" only counts when X actually reached the
reader — if it never became a post, there is nothing to repeat.

6. **"Covered by this post" means the post says it.** Checked in code, with no model: an
item is covered when the post repeats a detail only that item supplied. Anything else
goes back to waiting. 9 of 42 items marked covered in this channel's history had never
been in the post that claimed them.

7. **Fail-open design.** Sorter/gate errors → post anyway (safety). Only the editor can
reject, and it is the one station that fails closed. The cost of failing open is that a
model which cannot answer looks exactly like one that approves — which is why schema
failures are now counted per model and alert on a rate.

8. **Everything is auditable.** Every item has a status + reason. If something didn't post, you can see why (held, expired, rejected, low_impact, etc.).

---

## 🔧 Config Tuning (if needed)

Defaults live in \`config.py\`, but \`.env\` overrides them — read \`.env\` first, or you
will tune a number the running channel never sees.

- **\`COSINE_SHORTLIST\`** (0.72): what reaches the judge. Lower catches more rephrases at the cost of more LLM calls; 0.75 already started missing real duplicates.
- **\`COSINE_CERTAIN\`** (0.95): merged outright, no judge. Raise if you see wrong merges.
- **\`FUZZY_THRESHOLD\`** (92): how alike two headlines must be to count as the same wording.
- **\`MIN_IMPORTANCE\`** (4): the publishing bar. Raise = fewer posts, lower = more noise.
- **\`MAX_POSTS_PER_HOUR\`** (**4** — overridden in \`.env\`; the default in \`config.py\` is 12).
- **\`STORY_MIN_GAP_MINUTES\`** (6) and **\`STORY_MAX_POSTS\`** (12): per story, anti-double-post.
- **\`STORY_IDLE_HOURS\`** (36) / **\`STORY_MAX_HOURS\`** (168): when a story goes quiet, and its hard end.
- **\`STORY_DIGEST_ITEMS\`** (3) and **\`STORY_DIGEST_MINUTES\`** (180): how many held
  items, waiting how long, before the gate is asked about a roundup.
- **\`STORY_DIGEST_MAX_QUIET_HOURS\`** (12): past this much silence a story has stopped,
  and no roundup is asked about at all.
- **\`ECHO_WINDOW_HOURS\`** (120) and **\`ECHO_SHORTLIST\`** (0.72): how far back the exit
  check looks, and how alike two posts must be to reach its model.
- **\`ECHO_MODEL\`**: run \`tools/check_echo.py --labelled\` before changing it. This
  station fails open, so a model that cannot answer looks like one that says send.
`;
