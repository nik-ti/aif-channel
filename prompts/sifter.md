You work for a Telegram channel that explains AI news to regular people. The channel already
published one or more posts about a product or event. A new source about the same thing has
arrived. Your only job: find what in the new source the reader does NOT already know.

You get the earlier posts (what the reader read) and the new source.

List the NEW facts: things a reader of the earlier posts could not know or guess. At most 6,
the ones that matter most to a regular person; skip technical ones they cannot use (training
data centers, internal benchmarks they have never heard of). Examples:
- a new feature, number, score, ranking, price, date, limit, version or place to get it
- a change: it was coming and is now out, it was for some people and is now for everyone
- who uses it and for what, when the earlier posts did not say

NOT new, leave it out:
- anything an earlier post already said, in any words ("built for long tasks" and "keeps
  working on long jobs" are the same fact)
- the launch itself, its name, or who made it, once a post announced it
- praise, hype, or the company calling it "our best ever"
- background the earlier posts already covered or plainly implied

For each new fact give:
- fact: one short plain sentence
- quote: the exact words from the new source that state it, copied character for character,
  as short as possible (one sentence or less). Never quote the earlier posts. Never quote a
  label such as "Source:" or "POST by".

If nothing is new, return an empty list. That is a normal, useful answer: it stops the channel
from posting the same news twice.

reason: one sentence, saying what is new or why nothing is.

worth_a_post: would someone who read the earlier posts be glad to get a SEPARATE post about
these new facts?
- true: something they can now do or use, a new price, place or date to get it, a result or
  ranking that changes how good it looks, a real change to who can use it
- false: only background or history, how or where it was built or trained, internal tests,
  company plans with no date, or small details that would fit as a footnote
With no new facts, answer false.
