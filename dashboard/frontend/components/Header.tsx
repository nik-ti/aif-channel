// Sticky top bar: the channel's name, a help icon and the theme toggle.
// Light mode is the default on every fresh visit; the theme choice made here
// only sticks around in this browser via localStorage.
"use client";

import { Info, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

const THEME_KEY = "aif-theme";

export function Header() {
  const [dark, setDark] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

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
    <header className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b border-border bg-surface-primary px-4 py-2 sm:py-3">
      <div className="flex min-w-0 items-center gap-2">
        {/* The full name pushed the icons onto a second row at phone width. */}
        <span className="shrink-0 text-base font-semibold text-ink-primary">AI Flow</span>
        <span className="hidden truncate text-sm text-ink-muted sm:inline">@ai_flow_daily</span>
      </div>

      <div className="relative flex shrink-0 items-center gap-0.5 sm:gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="About this dashboard"
          onClick={() => setShowHelp((v) => !v)}
        >
          <Info className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          onClick={() => setDark((v) => !v)}
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        {showHelp && (
          <div className="absolute right-0 top-10 w-64 rounded-md border border-border bg-surface-primary p-3 text-xs text-ink-muted shadow-md">
            Live monitor over the AI Flow Telegram channel. Data refreshes every
            10 seconds from the channel&apos;s own database.
          </div>
        )}
      </div>
    </header>
  );
}
