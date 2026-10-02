# Media analysts: image analyst + video analyst

## What we're building
Two new stations in the pipeline. They decide what picture or clip, if any, goes
out with a post. The **image analyst** runs on both channels (Market One and AI
news). The **video analyst** runs on the AI news channel only. Both run on the
VPS inside the existing bot.

## Contract

GOAL: every post goes out with media that passed the analyst, or with no media
at all. Measured on a labelled set of at least 12 real images and 4 real videos,
the analyst agrees with the labels on at least 11 of 12 images and 4 of 4 videos.
"None of these is relevant" is a normal answer, not an error.

CONSTRAINTS:
- Uses the existing OpenRouter key only. Model: `google/gemini-2.5-flash` for both
  (measured on 2026-10-01: about $0.0007 per image, $0.003 for a 6 MB video).
- Markets channel: tweet videos and GIFs go out exactly as today, unchecked. The
  image analyst only judges posts that have images and no video.
- Article images and article videos are collected for the **AI channel only**.
- Nothing about the text pipeline changes: the analysts never edit or block a post.

FORMAT:
- `nodes/media.py`: collects the candidate images and videos for a post, from
  every item the post was written from (tweet media, plus article media on the AI
  channel).
- `nodes/image_analyst.py` and `nodes/video_analyst.py`: one station each,
  registered in STAGES, named in each channel's PIPELINE after `repeat_check`
  and before `publish`, so no money is spent on posts that get held.
- The rubrics are prompt files that can be edited without touching code:
  `channels/<name>/image_rubric.md` and `channels/ai_news/video_rubric.md`.
- The decision is stored on the post row (chosen media, its kind, the reason), so
  the dashboard can show why a picture was used or dropped.
- `tools/check_media.py --labelled`: the labelled set, run against the live model.

THE RUBRIC (agreed with nikita, 2026-10-01):
- Image REJECT: just shows a person (portraits, someone at a podium) · generic,
  stock or logo · another channel's branding, watermark, "BREAKING" template or
  meme · unreadable or low quality on a phone · doesn't match the post.
- Image ACCEPT only if it adds something the text can't, e.g. it shows the data
  (a clear chart or table of the post's number) or it is official source material
  (the company's own announcement or launch graphic).
- Several pass → the single best one goes out. Never an album.
- Video REJECT: longer than 2 minutes (checked in code, no model call) · doesn't
  show what the post says. Otherwise accept.
- A video that passes beats any image. The best passing image is the fallback if
  the video fails to send.

FAILURE (any of these = not done):
- A post goes out with an image the analyst rejected or never judged.
- When the model fails or times out, media still goes out. It must be sent with no media.
- A post is delayed or lost because of the analysts. The text always goes, on time.
- Markets videos change behaviour. They must stay exactly as today.
- An image showing only a person passes. The labelled set includes several.
- "None relevant" is logged as an error or alert. It's a normal outcome.
- A video over 2 minutes or 20 MB is sent to the model. That's checked in code first.
- Cost goes over $0.02 per post on average, measured over the labelled run.
- Every decision is logged, with the reason, on the post row.

## Built on top of
- OpenRouter `video_url` content parts (base64 MP4/MOV/WebM). With Gemini, direct
  file URLs fail and only YouTube links work, so files are downloaded first.
- `ffprobe` (already installed) for video length, read before any model call.
- trafilatura (already used) plus the page's `og:image` for article images.

## Gotchas we're handling
- Telegram fetches media by URL with a 20 MB cap. We skip anything bigger before
  judging it, because it couldn't be sent anyway.
- Article pages are full of icons, avatars and ads. We drop tiny images and
  tracking pixels, and cap the analyst at 6 images per post.
- Pages and tweets are untrusted. Text inside an image ("ignore your rules") is
  treated as content. The model answers in a fixed JSON schema and can only
  choose from the numbered candidates.
- Non-deterministic answers. Temperature is 0, and output is validated: an
  unknown index or bad JSON counts as a failure, which means no media.
- YouTube embeds inside articles can't be sent as a Telegram video, so they're
  out of scope for now. Only direct video files count.

## Build sequence
1. Tests first: `tests/test_media.py` (logic with the model faked) and the labelled
   set in `tools/check_media.py`. Both fail.
2. Store every candidate: all tweet images (today only the first is kept) and the
   chosen media on the post row (database migration).
3. Image analyst station plus the publisher using the post's chosen media. Both channels.
4. Article media collection (AI channel only).
5. Video analyst (AI channel only).
6. README, dashboard guide, labelled run, restart.

## How to run and test
- Tests (no model, free): `CHANNEL=markets /usr/bin/python3 tests/test_media.py`
- Labelled set (live model, about $0.05): `CHANNEL=markets /usr/bin/python3 tools/check_media.py --labelled`
- Setup: nothing new. `OPENROUTER_API_KEY` is already in `.env`.

## Status
_Updated: 2026-10-01_
- Built: all six phases. Live on Market One since 16:37 (first post: no candidates,
  sent as text, recorded on the row). Wired into the AI channel's PIPELINE, untested
  live because that channel has no sources yet.
- Verified: tests 21/21; labelled set 29/29 on two runs; worst case about $0.013 a
  post (6 images plus 2 clips), typical $0.0007.
- Changed from plan: the publisher now sends only media recorded on the post row, so
  an approved post from before this change, if it is retried, goes out as text.
  Article images are de-duplicated by address without the query (?w=, ?resize=).
- Next: when the AI channel launches, run `tools/check_media.py` with labelled AI
  examples (launch graphics, benchmark charts, founder photos) and add them.
- Watch out for: the rubric needed two fixes found by the labelled set. Tell the
  model the date ("May 2025" read as the future), and tell it not to fact-check
  ("a price chart is not market cap"). Re-run the set after any rubric edit.
