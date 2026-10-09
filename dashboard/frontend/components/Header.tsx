// Sticky glass top bar: the channel's name, a live indicator answering "is it running,
// and what went out today", and the theme toggle. The indicator reads /pulse, which the
// channel's feed polling keeps fresh every 10 minutes even when nothing new arrives.
"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { usePulse } from "@/hooks/useApi";
import { cn } from "@/lib/utils";

const THEME_KEY = "aif-theme";
// Feeds are polled every 10 minutes; past this the channel has stopped.
const STALE_MINUTES = 25;

function minutesSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const date = new Date((iso.includes("T") ? iso : iso.replace(" ", "T")) + "Z");
  return Number.isNaN(date.getTime()) ? null : (Date.now() - date.getTime()) / 60_000;
}

function ago(minutes: number | null): string {
  if (minutes === null) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function LiveIndicator() {
  const { data, isError } = usePulse();
  const sinceCheck = minutesSince(data?.last_check_at);
  const down = isError || (data?.ready && (sinceCheck === null || sinceCheck > STALE_MINUTES));
  const sincePost = minutesSince(data?.last_post_at);

  return (
    <div className="flex min-w-0 items-center gap-3 rounded-full border border-border bg-surface-primary px-3 py-1.5 text-xs text-ink-muted">
      <span className="flex shrink-0 items-center gap-1.5 font-medium text-ink-primary">
        <span className="relative flex h-2 w-2">
          {!down && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
          )}
          <span className={cn("relative inline-flex h-2 w-2 rounded-full", down ? "bg-red-500" : "bg-emerald-500")} />
        </span>
        {down ? "Stopped" : "Running"}
      </span>
      <span className="hidden truncate sm:inline">
        Last post {ago(sincePost)}
      </span>
      <span className="hidden shrink-0 md:inline">
        <span className="font-medium text-ink-primary">{data?.posts_today ?? "–"}</span> today
      </span>
      {(data?.waiting_digest ?? 0) > 0 && (
        <span className="hidden shrink-0 md:inline">
          <span className="font-medium text-ink-primary">{data?.waiting_digest}</span> waiting for digest
        </span>
      )}
    </div>
  );
}

export function Header() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved === "dark") setDark(true);
    } catch {
      // Storage can be unavailable (private browsing); light mode is fine.
    }
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
    } catch {
      // Non-fatal — the toggle still works for this page view.
    }
  }, [dark]);

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-surface-primary">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <a href="/" className="flex shrink-0 items-center gap-2.5" aria-label="AI Flow, posts">
          <span
            aria-hidden
            className="h-7 w-7 rounded-[10px] shadow-inner"
            style={{ background: "conic-gradient(from 210deg, #4f5bff, #35c7b0, #ffb38a, #4f5bff)" }}
          />
          <span className="font-display text-[15px] font-semibold text-ink-primary">AI Flow</span>
          <span className="hidden text-sm text-ink-muted lg:inline">@ai_flow_daily</span>
        </a>

        <div className="flex min-w-0 items-center gap-1.5">
          <LiveIndicator />
          <Button
            variant="ghost"
            size="icon"
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setDark((v) => !v)}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
