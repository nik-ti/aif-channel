// The Graph tab's write-up of how AI Flow (@ai_flow_daily) turns news into posts.
export const WORKFLOW_EXPLANATION = `
# AI Flow — how a post gets made (A to Z)

AI Flow posts AI news that **regular people can use**: freelancers, business owners,
designers, video makers, students. Every post has to make sense to a 12-year-old.
The prompts are plain text files in the project's prompts/ folder; every other setting
is in config.py.

## 1. Where the news comes from
Checked every 10 minutes:
- **Feeds:** OpenAI news, Anthropic news (a community-made feed, Anthropic has none),
  Hugging Face blog, AI/TLDR, Tom Dörr's repo posts, Future Tools news (it links to the
  original article and states each item's release date).
- **Watched pages** (sites with no feed): x.ai/news every hour, skills.sh trending every
  6 hours, skills.sh official company skills every 12 hours. Each page is read with a
  plain request first; if that fails or finds nothing, a stealth browser (crawl4ai)
  reads it instead. A link that was not on the page last time is a new story. The very
  first look at a page only remembers what is already there, so nothing old floods in.
- Items older than **48 hours** are ignored (AI/TLDR dates everything at midnight).
- **X posts** from OpenAI, Google DeepMind, Claude, ClaudeDevs, TestingCatalog and Tibor
  Blaho, read from the shared tweet relay as they are posted.

## 2. Dedup — have we already seen this?
Five checks, cheapest first: same link, same headline, nearly the same wording,
same subject (embeddings shortlist), then an AI judge reads both texts and rules
"same event", "a continuation" or "different". The last two look back **7 days**, because
a launch gets re-reported for days; the wording checks look back 24 hours, since "DAILY AI
BRIEF — Oct 7" and "— Oct 8" read almost the same but are different news.

A "same event" repeat is dropped if the earlier item went out, is on its way, or waits
for a digest. If the earlier one was turned down (scored too low, rejected by the editor),
the new one is let through: a fuller account may pass where a thin one did not.

## 3. Fetch article — read the full page, before anything is judged
Every item that is not a repeat gets its article read first, so the sorter judges the
real content and not a feed's one-line snippet. Three ways in, in order: a plain request, then the stealth browser, then a free reader
service (r.jina.ai) for pages behind a bot check that even the browser cannot pass,
which is OpenAI's whole site. A feed article whose **own page** is dated more than about
3 days ago is dropped here (Future Tools dates an item by when *they* listed it, so an old
launch can look new). While reading the page it also collects:
- **Pictures** on the page, and **video players** (Vimeo, YouTube) as clip candidates.
- **The product link:** on AI/TLDR pages, the first official link (the GitHub release,
  the company blog post), so the post links to the thing itself, not to AI/TLDR.

## 4. Labeler — what is it, and who made it?
A cheap model (Gemini Flash Lite, about $0.0007 an item) picks two labels, each from a
**fixed list**. Anything it answers that is not exactly on the list is stored as "other",
so a company can never be split into two spellings.
- **Kind:** new_product (a new standalone product from a listed company), new_model,
  feature (something new inside a product you already have), pricing (prices, plans,
  limits), tool (anything new from a maker not on the list), skill (anything from
  skills.sh, plugins and prompt packs for an AI assistant), guide (something to learn
  from), roundup (a list of several separate news items), other.
- **Company** — who *made* the thing, not who posted about it: OpenAI, Anthropic, Google,
  Microsoft, xAI, Meta, Apple, Amazon, Nvidia, Mistral, DeepSeek, Alibaba, Perplexity,
  Midjourney, Cursor, or other.

**A roundup is dropped here.** Each of its items arrives on its own from a better source.
The labels are checked against 75 hand-labelled items with tools/check_labels.py.

## 5. Sorter — is it worth posting?
Reads the headline, the feed's summary, the start of the article, today's date and the two
labels, and answers:
- **Who can use it today:** everyone, creators, business, students, developers, or none.
  **"none" caps the score at 3**, so research papers, benchmark scores, waitlists,
  funding and company drama never get posted.
- **Usefulness 1-5.** **4 or more is posted.** New models and price cuts from major AI
  companies are a 4 even when they are only for developers. Version updates, unknown
  developer repos and third-party guides to someone else's release are a 3.

**Daily limits per kind.** Guides and skills are useful, but a channel full of them reads like a
list: at most **2 of each a day, at least 3 hours apart**. One that passes the sorter but hits a
limit waits in the **reserve** (shown as **Daily limit**). When the limit allows another, a model
picks the most useful waiting one and it is posted; anything that waits more than 3 days is dropped.

**Not for this channel:** AI for fun or looks (beauty, fashion, dating, games), and general advice
that is not about AI even when it is packaged as an AI skill (marketing-copy methods, sales frameworks).

## 6. Company limit — has this company had its turn today?
Each company gets **2 posts a day** (UTC day). A third item from the same company waits
(shown as **Waiting for digest**). At **18:00 UTC** each company's waiting items go out as
**one post with a line per item** ("More from Anthropic today"); a single waiting item goes
out as a normal post. Anything that waits more than 30 hours is dropped.
**A 5/5 item always goes out at once**, and makers labelled "other" are never limited.
The Companies tab shows today's count per company, what is waiting and the digests sent.

(Until 9 October this step was the story organizer and gatekeeper, built for Market One's
running events. They are switched off; their code is kept in archive/market-one.)

## 7. Writer
Its own prompt (writer.md) plus the voice file (persona.md). The shape:
- a **bold first line** saying what it is and why the reader should care,
- two to four short "•" lines, or one or two short paragraphs, with **two or three key
  words in bold** (a name, a price, "free"),
- the link line last ("Try it here", "Read the guide here").

**When it happened.** An article's publish date is not the release date. The writer
may say "just launched" only when the source is the maker's own announcement, or the
source says when (Future Tools' "Release date" of today or yesterday). The editor
rejects any other timing claim as an invented fact.

**A company digest** is the one post with a line per item: the writer is told it is the
channel's own evening roundup and gives every waiting item its own "•" line.

**It never repeats itself.** The writer sees the channel's last 10 posts as "do not open or
phrase it like these", and if a post still starts with the same first two words as a recent
one ("Here's a…"), it is sent back for a different opening once.

**No emoji at all**, only the "•" bullet. No hype words, no capitals for shouting. The
writer never copies a link: it writes LINK and the publisher fills in the address.

## 8. Editor — is the post right?
Its own prompt (editor.md), on a different model from the writer. It checks the post
against the source and can only reject by naming a rule. This channel adds **JARGON**:
a word a 12-year-old would not know, left unexplained ("tokens" and "API" are fine).
A fixable rejection goes back to the writer, **up to 3 times**. The writer gets its
rejected draft back and changes **only the words the editor named**, instead of writing
the post again from scratch (that used to fix one fault and add a new one, like "free" or
"just launched"). Both the writer and the editor see **every earlier request**, so a fix
is not undone and the editor cannot ask for the opposite of what it asked before. A
rejection after the third rewrite, or for a rule that cannot be fixed, is final.

## 9. Repeat check
The exit: does this finished post tell the reader anything a post of the last 60 days
did not? If not, it is held.

## 10. Image analyst and video analyst
Gemini looks at every candidate picture and clip and picks the one that shows what the
post says, or none. Clips from video players are downloaded with **yt-dlp** (720p, at
most 20 MB); anything **over 2 minutes is refused** before the model sees it. A video
that passes beats any picture, and the best picture is the backup. yt-dlp updates itself
every Monday, and 3 failed downloads in a row send an alert.

## 11. Publish
Fills in the link, adds the signature ("AI Flow | Subscribe"), and sends the post with
the chosen media. **A post never links to X.** When the source is a tweet with no outside
link, a web search (Gemini with OpenRouter's search, ~2 cents) looks for a page where the
reader can **try** the thing: an app, a demo, a download. An announcement or blog post is
never used (the post already says what it would), only a "try it" link found on one. The
page must load, must not be on X, and must not be dated more than 14 days ago. If nothing
fits, the post goes out with no link line. A digest never has a link.
Pace: at most 30 posts an hour and 200 a day, 90 seconds apart.

## Reading an item on the Posts tab
Open an item and read **What happened** top to bottom: what the **sorter** decided and
why, what the **editor** decided about the written post and why, and the **outcome**.
`;
