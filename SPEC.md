# AI news channel (second channel on the Market One machinery)

## What we're building
A second Telegram channel that runs on the same code as Market One, and posts AI
news that regular people can use: freelancers, business owners, students,
creators. Think new ChatGPT features, a free tool for designers, an official
prompt guide. Coding-only and run-it-yourself model news is allowed, but rare.
Style reference: the Russian channel @incubeai_pro (teardown:
https://claude.ai/artifact/N81CNKHc3nzdpa2TVksV4A). Runs on the VPS as its own
service with `CHANNEL=ai_news`.

## Contract

GOAL: in a rehearsal (`tools/test_brain.py`) on real items from the AI sources,
at least 8 of 10 written posts pass the "a 12-year-old gets it" read (no
unexplained jargon, one clear benefit in the first line), each ends with a
working link to the thing itself (the tool, repo or announcement, not an
aggregator page), and Market One's prompts are byte-for-byte unchanged.

CONSTRAINTS:
- Same codebase, same graph (brain/graph.py). The channel is a folder,
  `channels/ai_news/`. Anything shared only grows an optional profile setting
  whose default is exactly today's Market One behaviour.
- Same OpenRouter key and models as Market One. No new paid services.
- Sources (agreed 2026-10-04): AI/TLDR, Show HN (50+ points), Tom Dörr's
  repo_posts, MindStudio blog, OpenAI news, Anthropic news (community feed, the
  site has none), Hugging Face blog.
- Not live until nikita creates the bot and channel and gives their names.

FORMAT:
- `channels/ai_news/`: profile.py (sources, topics, marks, pacing), rubric.md
  (what is worth posting), persona.md (voice), writer.md and editor.md (the
  writer's and editor's prompts for this channel), image and video rubrics.
- Post shape: one-line bold hook → 2-4 short "•" lines or one short paragraph
  → a call-to-action line linking the thing → the channel signature.
- Stations: dedup → sorter → fetch_article → story_organizer → gatekeeper →
  writer → editor → repeat_check → image_analyst → video_analyst → publish.

FAILURE (any of these = not done):
- Any Market One prompt, schema or emoji list changes (tests/fixtures hash).
- The AI writer or editor prompt still talks about crypto, markets,
  geopolitics or scheduled releases.
- The AI channel reads from Market One's tweet group, so tweets go missing
  from Market One.
- A post links to something other than the item's own link or the product
  link we extracted (a link from inside the scraped text).
- A post goes out without the signature, or with the signature twice.
- An item whose source page is a bot-check or empty is treated as the article.
- A post contains any emoji (the "•" bullet is the only symbol allowed).
- The 33 MB Tom Dörr feed is downloaded whole on every change.
- A research paper, benchmark score, funding round or drama scores 4+ (not
  usable by a regular person today).

## Built on top of
- Everything Market One already has: dedup, stories, editor, echo, media
  analysts (`SPEC` history in git: media analysts done 2026-10-01).
- Feeds: ai-tldr.dev/feed.xml (Atom, ~50 items, each page lists the official
  source link first), hnrss.org/show?points=50, tom-doerr.github.io/repo_posts
  /feed.xml (each entry has `<link rel="related">` to the repo),
  mindstudio.ai/rss.xml, openai.com/news/rss.xml, Olshansk/rss-feeds
  Anthropic feed on GitHub (community-run, fresh as of 2026-10-02),
  huggingface.co/blog/feed.xml.

## Gotchas we're handling
- x.ai/news blocks bots and its community feed stopped in May; Qwen's blog feed
  stopped in 2025; daily.dev has no public feed. Skipped. Later option: their X
  accounts through the tweet relay.
- skills.sh and claudemarketplaces.com have no feed. They're directories, not
  news, so they're left out of this round (would need "what's new since
  yesterday" scraping).
- Shared tweet stream: each channel gets its own reader group, and a channel
  with no X accounts doesn't read the stream at all.
- Feed dates: AI/TLDR stamps items at midnight, so the 24-hour "too old" cutoff
  is 48 hours on this channel.
- Tom Dörr's feed is 33 MB. We read only its first 1 MB and cut at the last
  complete entry. It also hasn't updated since 2026-09-25.
- Links: the writer never copies a link. It writes `href="LINK"` and the
  publisher fills in the product link (repo / official source) or the item's own
  address. Everything else is still stripped in code.
- Jargon: a JARGON rule in this channel's editor sends a post back for one
  rewrite if it uses a term a 12-year-old wouldn't know without explaining it.

## Build sequence
1. Tests first: `tests/test_ai_channel.py` (AI channel) and
   `tests/test_markets_unchanged.py` (prompt hashes). AI tests fail.
2. Profile hooks: writer/editor prompt paths, marks and bullet, sorter axis
   name, tweet group, article age, extra editor rules, signature, product link.
3. Sources: related-link parsing, byte cap, product link from AI/TLDR pages.
4. Content: rubric.md, persona.md, writer.md, editor.md.
5. Rehearsal on real items, read every post, tune, update Status.
6. Launch (needs bot token, channel id, channel name): service, labelled media
   run with AI examples.

## How to run and test
- Tests (free, no model): `CHANNEL=ai_news /usr/bin/python3 tests/test_ai_channel.py`
  and `CHANNEL=markets /usr/bin/python3 tests/test_markets_unchanged.py`
  (plus the old `CHANNEL=markets /usr/bin/python3 tests/test_media.py`).
- Collect real items: `CHANNEL=ai_news /usr/bin/python3 main.py initdb` then
  `CHANNEL=ai_news /usr/bin/python3 main.py collect --once`
- Rehearse (writes nothing, sends nothing, ~5 cents):
  `CHANNEL=ai_news /usr/bin/python3 tools/test_brain.py --limit 25`
- Setup to go live: `AI_TELEGRAM_BOT_TOKEN`, `AI_CHANNEL_ID`,
  `AI_NEWS_SIGNATURE_HTML` in `.env`; bot is an admin of the channel.

## Status
_Updated: 2026-10-04_
- Built: phases 1-5, and test posts are going to AI Flow (@ai_flow_daily, same bot
  as Market One, signature in .env). Tests: AI 23/23, Market One prompts
  unchanged 15/15, media 23/23.
- Changed from plan (nikita, mid-build): no emoji, only "•", with bold key words
  and blank lines. Pages without a feed are watched (nodes/fetch_pages.py:
  plain request, then stealth crawl4ai). Posts should carry media wherever possible.
- Media: OpenAI pages are behind a Cloudflare challenge even crawl4ai fails, so
  r.jina.ai reads them (text, and the HTML for pictures). Vimeo/YouTube players
  on a page are now clip candidates, downloaded with yt-dlp (720p, 20 MB, 2 min).
  Dots, before: no media. After: OpenAI's own screen recording (t.me/ai_flow_daily/5).
- Rehearsal 2 (69 real items): 4 posts approved, 4 sent back for jargon; developer
  clutter gone. The editor is strict on jargon, which kills token-price stories.
- Found and fixed: the shared tweet group would have split Market One's tweets;
  USE_ECONOMIC_CALENDAR was never read; the sorter had no date ("DevDay 2026"
  read as the future); the story placer merged two OpenAI products (now: one
  product = one story).
- Not covered: Qwen (no crawlable links), daily.dev (login), claudemarketplaces
  (digest stopped 2026-08-31). Tom Dörr's feed hasn't updated since 2026-09-25.
- 2026-10-04 later: "tokens"/"API" are not jargon here (nikita). Major labs' new
  models and price cuts are wanted even when developer-only (GPT-6.1 Sol posted,
  message 6). The editor sees its own earlier rejection on a rewrite (it had
  flip-flopped "tokens" → "units of text" → "tokens"). Hacker News removed;
  rehearsal queue cleared. yt-dlp: full path (systemd can't see ~/.local/bin),
  weekly cron update, alert after 3 failed downloads.
- Decided: no waiting for media from later sources; the page's own media is enough.
- Next: the service file for CHANNEL=ai_news, then X accounts.
