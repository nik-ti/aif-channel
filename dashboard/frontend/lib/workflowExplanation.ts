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

## 2. Dedup — have we already seen this?
Five checks, cheapest first: same link, same headline, nearly the same wording,
same subject (embeddings shortlist), then an AI judge reads both texts and rules
"same event", "a continuation" or "different".

## 3. Fetch article — read the full page, before anything is judged
Every item that is not a repeat gets its article read first, so the sorter judges the
real content and not a feed's one-line snippet. Three ways in, in order: a plain request, then the stealth browser, then a free reader
service (r.jina.ai) for pages behind a bot check that even the browser cannot pass,
which is OpenAI's whole site. While reading the page it also collects:
- **Pictures** on the page, and **video players** (Vimeo, YouTube) as clip candidates.
- **The product link:** on AI/TLDR pages, the first official link (the GitHub release,
  the company blog post), so the post links to the thing itself, not to AI/TLDR.

## 4. Sorter — is it worth posting?
Reads the headline, the feed's summary and the start of the article (and today's date) and answers three things:
- **Kind:** launch (a big company ships its own model or feature), tool (an app, site,
  plugin or skill someone made), resource (a guide, course or prompt pack), or other.
- **Who can use it today:** everyone, creators, business, students, developers, or none.
  **"none" caps the score at 3**, so research papers, benchmark scores, waitlists,
  funding and company drama never get posted.
- **Usefulness 1-5.** **4 or more is posted.** New models and price cuts from major AI
  companies are a 4 even when they are only for developers. Version updates, unknown
  developer repos and third-party guides to someone else's release are a 3.

**Daily limits.** Guides ("resource") and skill packs ("skill") are useful, but a channel full
of them reads like a list: at most **2 of each a day, at least 3 hours apart**. One that passes
the sorter but hits a limit waits in the **reserve** (shown as **Daily limit**). When the limit
allows another, a model picks the most useful waiting one by the rubric and it is written and
posted; anything that waits more than 3 days is dropped. New models, features and tools are not limited.

**Not for this channel:** AI for fun or looks (beauty, fashion, dating, games), and general advice
that is not about AI even when it is packaged as an AI skill (marketing-copy methods, sales frameworks).

## 5. Story organizer — which story is this?
On this channel **one story is one product or release**: a launch, its rollout, a
guide to it. Two announcements from the same company on the same day are two stories.

## 6. Gatekeeper — has the story moved?
It asks whether the story has moved since its last post: post, hold the item as fuel
for the story's next post, or "wrong story". It is shown related posts from the whole
channel, not only this story, so a repeat filed under a new story is still caught.

**When it happened.** An article's publish date is not the release date. The writer
may say "just launched" only when the source is the maker's own announcement, or the
source says when (Future Tools' "Release date" of today or yesterday). The editor
rejects any other timing claim as an invented fact.

## 7. Writer
Its own prompt (writer.md) plus the voice file (persona.md). The shape:
- a **bold first line** saying what it is and why the reader should care,
- two to four short "•" lines, or one or two short paragraphs, with **two or three key
  words in bold** (a name, a price, "free"),
- the link line last ("Try it here", "Read the guide here").

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
link, a web search (Gemini with OpenRouter's search, ~2 cents) looks for the maker's own
page, and prefers a demo that page links to. The page must load and must not be on X.
If nothing is found, the post goes out with no link line rather than a link to the tweet.
Pace: at most 30 posts an hour and 200 a day, 90 seconds apart.

## Reading an item on the Posts tab
Open an item and read **What happened** top to bottom: what the **sorter** decided and
why, what the **editor** decided about the written post and why, and the **outcome**.
`;
