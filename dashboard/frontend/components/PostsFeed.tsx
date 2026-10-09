// Posts tab (default tab): filterable, paginated feed of everything the
// pipeline has ingested. Polls every 10s via usePosts().
//
// Filters — source, status chips, keyword search — live in the URL
// (?source=, ?status=, ?q=), like the channel does, so they survive a tab
// switch or a reload and a filtered view can be shared as a link.
//
// Two layouts share one expand/collapse state: a table from sm: up (a mouse
// and a wide screen make a dense grid the fastest way to scan), and a card
// per post below that (a 7-column table at 375px pushed Title/Kind/Status
// off the right edge with no visible hint it could scroll).
"use client";

import { ChevronDown, ChevronRight, ExternalLink, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { DecisionTrail } from "@/components/DecisionTrail";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useItemAction, usePosts, useStats } from "@/hooks/useApi";
import { COPY } from "@/lib/copy";
import { FORCEABLE, STATUS_FILTERS } from "@/lib/status";
import type { PostItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;

// The query params this tab owns; page.tsx clears them on a channel switch.
export const POSTS_PARAMS = ["source", "company", "kind", "status", "q"] as const;

// "new_model" → "new model". Older items keep the pre-2026-10-09 kinds (launch, resource).
function kindLabel(kind: string) {
  return kind ? kind.replace(/_/g, " ") : "-";
}

function formatTime(iso: string | null) {
  if (!iso) return "-";
  // DB times are stored as naive UTC strings ("YYYY-MM-DD HH:MM:SS").
  const withZone = iso.includes("T") ? iso : `${iso.replace(" ", "T")}Z`;
  const date = new Date(withZone);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Marks every search term in `text`, case-insensitively — the same match
// rule the backend's LIKE uses, so what is highlighted is why it matched.
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length || !text) return <>{text}</>;
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-sm bg-amber-200/70 px-0.5 text-inherit dark:bg-amber-500/30">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        )
      )}
    </>
  );
}

function ImportanceDots({ value, label = "Market impact" }: { value: number; label?: string }) {
  if (!value) return <span className="text-ink-muted">-</span>;
  return (
    <span className="inline-flex items-center gap-0.5" title={`${label} ${value} of 5`} aria-label={`${label} ${value} of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={cn("h-1.5 w-1.5 rounded-full", n <= value ? "bg-ink-primary" : "bg-border")}
        />
      ))}
    </span>
  );
}

// The expanded detail, shared by the card and the table row: full text,
// the pipeline's metadata and reason, and the override actions.
function PostDetail({ item, terms }: { item: PostItem; terms: string[] }) {
  const action = useItemAction();
  const [confirming, setConfirming] = useState<"force" | "regret" | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const canForce = FORCEABLE.has(item.status);
  const canRegret = item.status === "published";

  function run(kind: "force" | "regret") {
    setMessage(null);
    action.mutate(
      { kind, itemId: item.id, note },
      {
        onSuccess: () => {
          setConfirming(null);
          setNote("");
          setMessage({
            ok: true,
            text:
              kind === "force"
                ? "Back in the queue — the pipeline picks it up within a couple of minutes."
                : "Recorded as a post that should not have gone out.",
          });
        },
        onError: (error) => setMessage({ ok: false, text: error.message }),
      }
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-primary">
        {item.body ? <Highlight text={item.body} terms={terms} /> : "(no body text)"}
      </p>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-5">
        <div>
          <dt className="text-ink-muted">{COPY.importance}</dt>
          <dd className="mt-0.5"><ImportanceDots value={item.importance} label={COPY.importance} /></dd>
        </div>
        <div>
          <dt className="text-ink-muted">{COPY.market}</dt>
          <dd className="mt-0.5 text-ink-primary">{item.market || "-"}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Kind</dt>
          <dd className="mt-0.5 text-ink-primary">{kindLabel(item.topic)}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Made by</dt>
          <dd className="mt-0.5 text-ink-primary">{item.company || "-"}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Arrived</dt>
          <dd className="mt-0.5 text-ink-primary">{formatTime(item.time)}</dd>
        </div>
      </dl>

      <DecisionTrail item={item} />

      <div className="flex flex-wrap items-center gap-2">
        {item.telegram_url && (
          <a
            href={item.telegram_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center gap-1.5 rounded-md border border-sky-300 bg-sky-50 px-3 text-xs font-medium text-sky-800 hover:bg-sky-100 sm:h-8"
          >
            View in Telegram <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-medium text-ink-primary hover:bg-surface-secondary sm:h-8"
          >
            Open source <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
        {canForce && confirming !== "force" && (
          <Button variant="outline" size="sm" onClick={() => setConfirming("force")}>
            Overrule &amp; publish
          </Button>
        )}
        {canRegret && confirming !== "regret" && (
          <Button variant="outline" size="sm" onClick={() => setConfirming("regret")}>
            Shouldn&apos;t have posted
          </Button>
        )}
      </div>

      {confirming && (
        <div className="flex flex-col gap-2 rounded-md border border-border p-3">
          <p className="text-xs text-ink-muted">
            {confirming === "force"
              ? "Sends this item back to the queue, skipping the checks that rejected it. It goes out on the next round."
              : "Labels this post as a mistake for later prompt tuning. Nothing is deleted from Telegram."}
          </p>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why? (optional, helps later tuning)"
            className="h-11 rounded-md border border-border bg-surface-primary px-3 text-sm text-ink-primary outline-none focus:ring-2 focus:ring-sky-500 sm:h-9"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={confirming === "regret" ? "destructive" : "default"}
              disabled={action.isPending}
              onClick={() => run(confirming)}
            >
              {action.isPending ? "Saving…" : "Confirm"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {message && (
        <p role="status" className={cn("text-xs", message.ok ? "text-status-published" : "text-status-rejected")}>
          {message.text}
        </p>
      )}
    </div>
  );
}

function PostCard({
  item,
  terms,
  isOpen,
  onToggle,
}: {
  item: PostItem;
  terms: string[];
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-primary">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-label={isOpen ? "Collapse full post" : "View full post"}
        className="flex min-h-[44px] w-full items-start justify-between gap-3 p-4 text-left"
      >
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
            <StatusBadge status={item.status} />
            <span>{item.source_name}</span>
            <span aria-hidden>&middot;</span>
            <span>{formatTime(item.time)}</span>
            {item.topic && (
              <>
                <span aria-hidden>&middot;</span>
                <span>{kindLabel(item.topic)}{item.company && item.company !== "other" ? ` · ${item.company}` : ""}</span>
              </>
            )}
          </div>
          <p className="text-sm font-medium text-ink-primary">
            <Highlight text={item.title} terms={terms} />
          </p>
        </div>
        {isOpen ? (
          <ChevronDown className="mt-1 h-5 w-5 shrink-0 text-ink-muted" />
        ) : (
          <ChevronRight className="mt-1 h-5 w-5 shrink-0 text-ink-muted" />
        )}
      </button>
      {isOpen && (
        <div className="border-t border-border p-4 pt-3">
          <PostDetail item={item} terms={terms} />
        </div>
      )}
    </div>
  );
}

// Reads and writes this tab's filters in the URL.
function usePostFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const source = searchParams.get("source");
  const company = searchParams.get("company");
  const kind = searchParams.get("kind");
  const statusIds = useMemo(
    () => (searchParams.get("status") ?? "").split(",").filter((id) => STATUS_FILTERS.some((f) => f.id === id)),
    [searchParams]
  );
  const q = searchParams.get("q") ?? "";

  const update = useCallback(
    (changes: Partial<Record<(typeof POSTS_PARAMS)[number], string | null>>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value) params.set(key, value);
        else params.delete(key);
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams]
  );

  return { source, company, kind, statusIds, q, update };
}

export function PostsFeed() {
  const { source, company, kind, statusIds, q, update } = usePostFilters();
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [searchText, setSearchText] = useState(q);

  // The box updates instantly; the URL (and so the query) follows once the
  // typing pauses, instead of one request per keystroke. `pushed` is the
  // last value this box wrote, so a URL change from anywhere else (back
  // button, "Clear filters", a channel switch) can be told apart from our
  // own write landing while the user is still typing.
  const pushed = useRef(q);
  useEffect(() => {
    const next = searchText.trim();
    if (next === pushed.current) return;
    const timer = setTimeout(() => {
      pushed.current = next;
      update({ q: next || null });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchText, update]);

  useEffect(() => {
    if (q === pushed.current) return;
    pushed.current = q;
    setSearchText(q);
  }, [q]);

  // Any filter change starts over at page one.
  const filterKey = `${source}|${company}|${kind}|${statusIds.join(",")}|${q}`;
  useEffect(() => {
    setPage(0);
  }, [filterKey]);

  const statuses = useMemo(
    () => STATUS_FILTERS.filter((f) => statusIds.includes(f.id)).flatMap((f) => f.statuses),
    [statusIds]
  );
  const terms = useMemo(() => q.split(/\s+/).filter(Boolean), [q]);

  const { data: stats } = useStats();
  const { data, isFetching, dataUpdatedAt } = usePosts(
    { source, company, kind, statuses, q },
    PAGE_SIZE,
    page * PAGE_SIZE
  );

  if (data && !data.ready) {
    return (
      <div className="p-4">
        <EmptyState />
      </div>
    );
  }

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleStatus(id: string) {
    const next = statusIds.includes(id) ? statusIds.filter((s) => s !== id) : [...statusIds, id];
    update({ status: next.length ? next.join(",") : null });
  }

  const counts = data?.status_counts ?? {};
  const chipCount = (statusesOfChip: string[]) => statusesOfChip.reduce((n, s) => n + (counts[s] ?? 0), 0);
  const allCount = Object.values(counts).reduce((a, b) => a + b, 0);

  const sources = stats?.sources_count.map((s) => s.source_name) ?? [];
  const companies = stats?.companies.map((c) => c.company) ?? [];
  const kinds = stats?.kinds.map((k) => k.kind) ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstShown = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastShown = Math.min(total, (page + 1) * PAGE_SIZE);
  const hasFilters = Boolean(source || company || kind || statusIds.length || q);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Search + source */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
          <input
            type="search"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search titles and text…"
            aria-label="Search posts by keyword"
            enterKeyHint="search"
            className="h-11 w-full rounded-md border border-border bg-surface-primary pl-9 pr-9 text-sm text-ink-primary outline-none placeholder:text-ink-muted focus:ring-2 focus:ring-sky-500 sm:h-9 [&::-webkit-search-cancel-button]:hidden"
          />
          {searchText && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setSearchText("");
                update({ q: null });
              }}
              className="absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded text-ink-muted hover:text-ink-primary sm:h-7 sm:w-7"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <select
          value={source ?? ""}
          onChange={(e) => update({ source: e.target.value || null })}
          aria-label="Source"
          className="h-11 rounded-md border border-border bg-surface-primary px-3 text-sm text-ink-primary sm:h-9"
        >
          <option value="">All sources</option>
          {sources.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <select
            value={company ?? ""}
            onChange={(e) => update({ company: e.target.value || null })}
            aria-label="Company"
            className="h-11 flex-1 rounded-md border border-border bg-surface-primary px-3 text-sm text-ink-primary sm:h-9 sm:flex-none"
          >
            <option value="">All companies</option>
            {companies.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <select
            value={kind ?? ""}
            onChange={(e) => update({ kind: e.target.value || null })}
            aria-label="Kind"
            className="h-11 flex-1 rounded-md border border-border bg-surface-primary px-3 text-sm text-ink-primary sm:h-9 sm:flex-none"
          >
            <option value="">All kinds</option>
            {kinds.map((name) => (
              <option key={name} value={name}>
                {kindLabel(name)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Status chips — scroll sideways on a phone rather than wrapping into
          four rows above the feed. */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
        <button
          type="button"
          onClick={() => update({ status: null })}
          aria-pressed={statusIds.length === 0}
          className={cn(
            "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors sm:h-8",
            statusIds.length === 0
              ? "border-ink-primary bg-ink-primary text-surface-primary"
              : "border-border bg-surface-primary text-ink-primary hover:bg-surface-secondary"
          )}
        >
          All <span className="tabular-nums opacity-70">{allCount}</span>
        </button>
        {STATUS_FILTERS.map((f) => {
          const active = statusIds.includes(f.id);
          const n = chipCount(f.statuses);
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => toggleStatus(f.id)}
              aria-pressed={active}
              className={cn(
                "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors sm:h-8",
                active
                  ? "border-ink-primary bg-surface-primary text-ink-primary ring-1 ring-ink-primary"
                  : "border-border bg-surface-primary text-ink-primary hover:bg-surface-secondary",
                !active && n === 0 && "opacity-50"
              )}
            >
              <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: f.color }} />
              {f.label}
              <span className="tabular-nums text-ink-muted">{n}</span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
        <span>
          {total === 0 ? "No matches" : `Showing ${firstShown}–${lastShown} of ${total}`}
          {hasFilters && (
            <>
              {" · "}
              <button
                type="button"
                onClick={() => {
                  setSearchText("");
                  update({ source: null, company: null, kind: null, status: null, q: null });
                }}
                className="font-medium text-ink-primary underline-offset-2 hover:underline"
              >
                Clear filters
              </button>
            </>
          )}
        </span>
        <span>{isFetching ? "Refreshing…" : `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}`}</span>
      </div>

      {/* Cards below sm: — a 7-column table at phone width pushed Title,
          Kind and Status off the right edge with no visible scroll hint. */}
      <div className="flex flex-col gap-3 sm:hidden">
        {data?.items.map((item) => (
          <PostCard
            key={item.id}
            item={item}
           
            terms={terms}
            isOpen={expanded.has(item.id)}
            onToggle={() => toggleExpanded(item.id)}
          />
        ))}
        {data?.items.length === 0 && (
          <p className="py-8 text-center text-sm text-ink-muted">No posts for this filter.</p>
        )}
      </div>

      <div className="table-scroll hidden rounded-lg border border-border bg-surface-primary sm:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Time</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Made by</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((item) => {
              const isOpen = expanded.has(item.id);
              return (
                <Fragment key={item.id}>
                  <TableRow
                    className="cursor-pointer hover:bg-surface-secondary"
                    onClick={() => toggleExpanded(item.id)}
                  >
                    <TableCell className="text-ink-muted">
                      <button
                        type="button"
                        aria-label={isOpen ? "Collapse full post" : "View full post"}
                        title={isOpen ? "Collapse full post" : "View full post"}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpanded(item.id);
                        }}
                        className="rounded p-0.5 hover:bg-surface-secondary"
                      >
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-muted" title={`Item #${item.id}`}>
                      {formatTime(item.time)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{item.source_name}</TableCell>
                    <TableCell className="max-w-md truncate" title={item.title}>
                      <Highlight text={item.title} terms={terms} />
                    </TableCell>
                    <TableCell>
                      <ImportanceDots value={item.importance} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-muted">{kindLabel(item.topic)}</TableCell>
                    <TableCell className="whitespace-nowrap text-ink-muted">{item.company || "-"}</TableCell>
                    <TableCell>
                      <StatusBadge status={item.status} />
                    </TableCell>
                  </TableRow>
                  {isOpen && (
                    <TableRow className="bg-surface-secondary/60 hover:bg-surface-secondary/60">
                      <TableCell colSpan={8} className="whitespace-normal py-4">
                        <p className="mb-2 font-semibold text-ink-primary">
                          <Highlight text={item.title} terms={terms} />
                          <span className="ml-2 text-xs font-normal text-ink-muted">#{item.id}</span>
                        </p>
                        <PostDetail item={item} terms={terms} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
            {data?.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-ink-muted">
                  No posts for this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-ink-muted">
        <span>
          Page {page + 1} of {totalPages}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
