// Companies tab: the daily limit per company at a glance. Today's posts per company
// against the limit, the items waiting for tonight's digest, and the digests already
// sent with the items each one covered. Replaces the old Stories tab (2026-10-09).
"use client";

import { ExternalLink } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCompanies } from "@/hooks/useApi";
import { STATUS_INFO } from "@/lib/status";
import { cn } from "@/lib/utils";

function toDate(iso: string | null) {
  if (!iso) return null;
  const date = new Date((iso.includes("T") ? iso : iso.replace(" ", "T")) + "Z");
  return Number.isNaN(date.getTime()) ? null : date;
}

function localTime(iso: string | null) {
  const date = toDate(iso);
  return date ? date.toLocaleString() : "-";
}

// The digest hour is stored in UTC; show it in the viewer's own clock too.
function digestTime(hourUtc: number) {
  const date = new Date();
  date.setUTCHours(hourUtc, 0, 0, 0);
  return `${String(hourUtc).padStart(2, "0")}:00 UTC (${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} your time)`;
}

export function CompaniesView() {
  const { data, isFetching } = useCompanies();

  if (data && !data.ready) {
    return (
      <div className="p-4">
        <EmptyState />
      </div>
    );
  }

  const limit = data?.limit ?? 2;

  if (!data) {
    return <p className="p-6 text-sm text-ink-muted">Loading today&apos;s companies…</p>;
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
        <h2 className="font-display text-xl font-semibold text-ink-primary">Companies</h2>
        <p className="mt-0.5 max-w-2xl text-sm text-ink-muted">
          Each company gets <span className="font-semibold text-ink-primary">{limit} posts a day</span> (UTC).
          The rest wait and go out together at{" "}
          <span className="font-semibold text-ink-primary">{data ? digestTime(data.digest_hour_utc) : "…"}</span>.
          A 5/5 launch always goes out.
        </p>
        </div>
        {isFetching && <span className="text-xs text-ink-muted">Refreshing…</span>}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Posts today</CardTitle>
        </CardHeader>
        <CardContent>
          {data && data.today.length === 0 ? (
            <p className="text-sm text-ink-muted">No company has posted yet today.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {data?.today.map((row) => {
                const full = row.posts_today >= limit;
                return (
                  <li key={row.company} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <span className="w-28 shrink-0 font-medium text-ink-primary">{row.company}</span>
                    <span className="flex gap-1" aria-label={`${row.posts_today} of ${limit} posts`}>
                      {Array.from({ length: Math.max(limit, row.posts_today) }).map((_, i) => (
                        <span
                          key={i}
                          className={cn("h-2.5 w-6 rounded-full", i < row.posts_today ? "" : "bg-surface-secondary")}
                          style={i < row.posts_today ? { background: STATUS_INFO.published.color } : undefined}
                        />
                      ))}
                    </span>
                    <span className="text-xs text-ink-muted">
                      {row.posts_today} of {limit}
                      {full ? " · limit reached" : ""}
                      {row.waiting ? ` · ${row.waiting} waiting` : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>
            Waiting for the digest <span className="font-normal text-ink-muted">{data?.waiting.length ?? 0}</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data && data.waiting.length === 0 ? (
            <p className="text-sm text-ink-muted">Nothing is waiting.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {data?.waiting.map((item) => (
                <li key={item.id} className="flex flex-col gap-0.5 py-2">
                  <span className="flex flex-wrap gap-x-3 text-xs text-ink-muted">
                    <span className="font-medium text-ink-primary">{item.company}</span>
                    <span>{item.kind.replace(/_/g, " ")}</span>
                    <span>scored {item.importance}/5</span>
                    <span>arrived {localTime(item.time)}</span>
                  </span>
                  <span className="text-sm text-ink-primary">{item.title}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Digests sent</CardTitle>
        </CardHeader>
        <CardContent>
          {data && data.digests.length === 0 ? (
            <p className="text-sm text-ink-muted">No digest has gone out yet.</p>
          ) : (
            <ul className="flex flex-col gap-4">
              {data?.digests.map((digest) => (
                <li key={digest.id} className="flex flex-col gap-2 rounded-xl bg-surface-secondary p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
                    <span className="flex flex-wrap gap-x-3">
                      <span className="font-medium text-ink-primary">{digest.company}</span>
                      <span>{localTime(digest.sent_at)}</span>
                      <span>{digest.items.length} items</span>
                    </span>
                    {digest.telegram_url && (
                      <a
                        href={digest.telegram_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                      >
                        View in Telegram <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-primary">{digest.text}</p>
                  <details className="text-xs text-ink-muted">
                    <summary className="cursor-pointer">Items in it</summary>
                    <ul className="mt-1 list-disc pl-5">
                      {digest.items.map((item) => (
                        <li key={item.id}>
                          {item.title} <span className="opacity-60">#{item.id}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
