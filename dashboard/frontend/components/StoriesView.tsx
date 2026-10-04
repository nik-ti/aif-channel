// Stories tab: every story as a card — its name, whether it's still live,
// how much it has told the reader vs. how much it's holding back, and its
// most recent post. Expanding a card shows every item filed under it in
// full (title, body, status, the pipeline's reason). Live stories first,
// closed ones collapsed below so the tab stays scannable once a channel has
// history.
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { DecisionTrail } from "@/components/DecisionTrail";
import { StatusBadge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useStories } from "@/hooks/useApi";
import { STATUS_INFO } from "@/lib/status";
import type { Story, StoryPost } from "@/lib/types";
import { cn } from "@/lib/utils";

function toDate(iso: string | null) {
  if (!iso) return null;
  const date = new Date((iso.includes("T") ? iso : iso.replace(" ", "T")) + "Z");
  return Number.isNaN(date.getTime()) ? null : date;
}

// "3h ago" / "2d ago" for the card face; the exact timestamp still shows up
// as a tooltip so nothing is lost, only compressed.
function timeAgo(iso: string | null): string | null {
  const date = toDate(iso);
  if (!date) return null;
  const minutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.round(days / 30)}mo ago`;
}

function absoluteTime(iso: string | null) {
  const date = toDate(iso);
  return date ? date.toLocaleString() : iso ?? "";
}

// Green dot while the story can still take new items, gray once it's closed
// — the same "active vs. done" colors the rest of the dashboard uses.
function StateTag({ state }: { state: string }) {
  const live = state === "live";
  const color = live ? STATUS_INFO.published.color : STATUS_INFO.expired.color;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color }}>
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", live && "animate-pulse")} style={{ background: color }} />
      {live ? "Live" : "Closed"}
    </span>
  );
}

// The ratio the owner asked for at a glance: how much of what the story
// collected actually went out. A story sitting on unposted items gets the
// same amber "held" color the Posts tab already uses for that state.
function HoldMeter({ postCount, itemCount, declinedCount }: {
  postCount: number; itemCount: number; declinedCount: number;
}) {
  const total = Math.max(itemCount, postCount, 1);
  const pct = Math.min(100, Math.round((postCount / total) * 100));
  // What is waiting, not counting drafts the editor threw out — those are
  // shown separately, because "held" and "rejected" are different problems.
  const held = Math.max(0, itemCount - postCount - declinedCount);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${pct}%`, background: STATUS_INFO.published.color }}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
        <span className="tabular-nums">
          {postCount} published of {itemCount} item{itemCount === 1 ? "" : "s"}
        </span>
        {declinedCount > 0 && (
          <span
            className="inline-flex items-center gap-1.5 font-medium"
            style={{ color: STATUS_INFO.declined.color }}
            title="Posts the writer produced and the editor rejected — never sent"
          >
            <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_INFO.declined.color }} />
            {declinedCount} rejected
          </span>
        )}
        {held > 0 && (
          <span
            className="inline-flex items-center gap-1.5 font-medium"
            style={{ color: STATUS_INFO.held.color }}
            title="Items filed under this story that haven't gone out as their own post yet"
          >
            <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_INFO.held.color }} />
            holding {held} back
          </span>
        )}
      </div>
    </div>
  );
}

function StoryPostRow({ post, channel }: { post: StoryPost; channel: string }) {
  const label = post.status === "published" ? "Post" : "Item";
  return (
    <div className="flex flex-col gap-1.5 border-t border-border py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <span className="font-medium text-ink-primary">{label}</span>
        <StatusBadge status={post.status} />
        <span>#{post.item_id}</span>
      </div>
      <p className="text-sm font-medium text-ink-primary">{post.title}</p>
      {post.body && post.body !== post.title && (
        <p className="whitespace-pre-wrap break-words text-sm text-ink-muted">{post.body}</p>
      )}
      <DecisionTrail item={post} channel={channel} />
      {post.telegram_url && (
        <a
          href={post.telegram_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-0.5 inline-flex h-8 w-fit items-center gap-1.5 rounded-md border border-sky-300 bg-sky-50 px-2.5 text-xs font-medium text-sky-800 hover:bg-sky-100"
        >
          View in Telegram <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </div>
  );
}

function StoryCard({ story, channel }: { story: Story; channel: string }) {
  const [open, setOpen] = useState(false);
  const title = story.name || story.headline;
  const ago = timeAgo(story.last_post_at);
  const running = timeAgo(story.first_at);

  return (
    <Card>
      <CardHeader className="gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <StateTag state={story.state} />
              <span className="text-xs text-ink-muted" title={absoluteTime(story.last_post_at)}>
                {ago ? `Posted ${ago}` : "Nothing published yet"}
              </span>
              {running && (
                <span className="text-xs text-ink-muted" title={absoluteTime(story.first_at)}>
                  Running {running.replace(" ago", "")}
                </span>
              )}
            </div>
            <h3 className="break-words text-base font-semibold leading-snug text-ink-primary">{title}</h3>
          </div>
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
          )}
        </button>

        <HoldMeter postCount={story.post_count} itemCount={story.item_count} declinedCount={story.declined_count} />

        {story.summary && (
          <div className="rounded-md bg-surface-secondary px-3 py-2">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-muted">Last told the reader</p>
            <p className="whitespace-pre-wrap break-words text-sm text-ink-primary">{story.summary}</p>
          </div>
        )}
      </CardHeader>
      {open && (
        <CardContent className="pt-0">
          {story.posts.length === 0 ? (
            <p className="text-sm text-ink-muted">No items in this story yet.</p>
          ) : (
            <div className="flex flex-col">
              {story.posts.map((post) => (
                <StoryPostRow key={post.item_id} post={post} channel={channel} />
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

export function StoriesView({ channel }: { channel: string }) {
  const { data, isFetching } = useStories(channel);
  const [showClosed, setShowClosed] = useState(false);

  if (data && !data.ready) {
    return (
      <div className="p-4">
        <EmptyState channel={channel} />
      </div>
    );
  }

  const live = data?.stories.filter((s) => s.state === "live") ?? [];
  const closed = data?.stories.filter((s) => s.state !== "live") ?? [];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink-primary">Active stories ({live.length})</h2>
        {isFetching && <span className="text-xs text-ink-muted">Refreshing...</span>}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {live.map((story) => (
          <StoryCard key={story.id} story={story} channel={channel} />
        ))}
        {live.length === 0 && <p className="text-sm text-ink-muted">No active stories right now.</p>}
      </div>

      <div>
        <button
          onClick={() => setShowClosed((v) => !v)}
          className="flex min-h-[44px] w-full items-center gap-1.5 text-sm font-semibold text-ink-primary"
        >
          {showClosed ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Closed stories ({closed.length})
        </button>
        {showClosed && (
          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
            {closed.map((story) => (
              <StoryCard key={story.id} story={story} channel={channel} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
