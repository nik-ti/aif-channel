# Market One (@market_one_news), paused 2026-10-07

Market One was an automated Telegram channel for market-moving news: crypto, markets and
geopolitics. It ran from 2026-07-28 to 2026-10-06 from the same code as AI Flow, sent
599 posts and processed 11,745 items. nikita paused it to focus on AI Flow. The project
was then cut down to AI Flow alone, so the running code no longer knows about Market One.
This folder and a git tag are everything needed to bring it back.

## What is where

| Thing | Where |
|---|---|
| **Exact working code** (both channels, multi-channel machinery, dashboard switcher) | git tag **`market-one-final`** (commit 6183763) |
| Settings: sources, X accounts, topics, markets axis, models, pipeline order | `settings.py` (was `channels/markets/profile.py`) |
| Sorter rubric (rewritten 2026-10-06 around "which major asset moves?") | `prompts/rubric.md` |
| Voice | `prompts/persona.md` |
| Writer prompt template + length rules + emoji marks | `prompts/writer.md`, `prompts/writer_length_rules.md` |
| Editor prompt | `prompts/editor.md` |
| How to read a macro release (fed to writer and editor) | `prompts/market_reading.md` |
| Which pictures may go out | `prompts/image_rubric.md` |
| Economic calendar (scheduled releases, Forecast/Previous lines) | `code/calendar.py` |
| Tests that existed only for Market One | `code/test_macro.py`, `code/test_markets_unchanged.py` |
| Database layout at pause (includes the `calendar` table and calendar columns) | `schema.sql` |
| systemd unit and log rotation | `deploy/` |
| The full README of both channels at pause, and the last spec | `README-both-channels-2026-10-06.md`, `SPEC-rubric-and-models-2026-10-06.md` |
| **Database** (11,745 items, 599 posts, stories, reader memory) and logs | `data/` here, on the VPS only. Never on GitHub (101 MB, gitignored). |

## The graph (LangGraph, at pause)

```mermaid
graph LR
    start --> dedup
    dedup -->|drop| end
    dedup -->|sort| sorter
    sorter -->|end| end
    sorter -->|place| fetch_article
    fetch_article --> story_organizer
    story_organizer -->|end| end
    story_organizer -->|gate| gatekeeper
    gatekeeper -->|end| end
    gatekeeper -->|write| writer
    writer -->|end| end
    writer -->|edit| editor
    editor -->|end| end
    editor -->|rewrite| writer
    editor -->|publish| repeat_check
    repeat_check -->|end| end
    repeat_check -->|send| image_analyst
    image_analyst --> publish
    publish --> end
```

AI Flow's graph differs in three ways: it fetches the article before the sorter, has a video
analyst, and has a reserve for daily-capped topics. Everything else is shared.

## Models at pause (all via OpenRouter)

| Station | Model | Note |
|---|---|---|
| Sorter | `google/gemini-3.5-flash-lite` | 100% schema, agreed with nikita 43/49, ~$3/month |
| Writer | `openai/gpt-6-luna` | 31/40 editor-approved, ~$0.0003/post |
| Dedup judge, story placement and gate, image analyst | `google/gemini-2.5-flash` | |
| Editor | `mistralai/mistral-medium-3.1`, fallback `minimax/minimax-m2.7` | must be a different lab from the writer |
| Repeat check | `mistralai/mistral-medium-3.1` | |
| Embeddings | `openai/text-embedding-3-small` | |

Cost at pause: about $7/month at ~200 items per weekday.

## Outside this folder

- **.env keys** it used: `TELEGRAM_BOT_TOKEN`, `CHANNEL_ID` (@market_one_news),
  `ERROR_CHAT_ID`, `OPENROUTER_API_KEY`, `MAX_POSTS_PER_HOUR=4`. The bot token was not
  copied anywhere; reuse the Market One bot from BotFather.
- **X accounts** come from the shared tweet relay (`/home/nikita/trading/infra/tweet-relay/`).
  The accounts in `settings.py` must also be in the relay's `accounts.txt`. Market One read the
  Redis stream `tweets:stream` with the consumer group `news-channel`, which still exists.
- **systemd unit** `market-one-channel` is stopped and disabled. Its unit file still points at
  the old folder `/home/nikita/systems/news-channels`, which no longer exists.

## How to bring it back

**Quickest (run it as it was, on its own):**
1. `git clone git@github.com:nik-ti/aif-channel.git market-one && cd market-one && git checkout market-one-final`
   (the repo may still be named `market-one-channel`).
2. Copy `.env` keys above into `market-one/.env`, and move `archive/market-one/data/markets.db`
   to `market-one/data/markets.db`.
3. Install `deploy/market-one-channel.service` with its paths changed to the new folder, set
   `Environment=CHANNEL=markets`, then `systemctl enable --now`.
4. Its dashboard at that tag still has the channel switcher; it reads `data/markets.db`.

**Better long-term (one codebase again):** add it to AI Flow's single-channel code as a second
channel. Port `settings.py` into config, give the sorter/writer/editor a per-channel prompt
folder (as in `prompts/` here), restore `code/calendar.py` and its hooks in the sorter, writer,
editor and collect loop (see the tag's `nodes/` for exactly where), and add a channel field to
the dashboard. The tag's `config.py` shows how the two-channel version did it with
`channels/<name>/profile.py` and a `CHANNEL` env var.
