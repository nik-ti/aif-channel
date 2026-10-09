// The five tabs as one glass pill. Switching is local state in page.tsx; this only
// renders the strip and reports clicks upward.
"use client";

import { cn } from "@/lib/utils";

export const TABS = ["Posts", "Companies", "Stats", "Graph", "Nodes"] as const;
export type Tab = (typeof TABS)[number];

export function TabNav({
  active,
  onChange,
}: {
  active: Tab;
  onChange: (tab: Tab) => void;
}) {
  return (
    <nav className="mx-auto max-w-7xl px-4 pt-5 sm:px-6" aria-label="Sections">
      <div className="glass-panel flex w-full gap-0.5 overflow-x-auto rounded-full p-1 sm:inline-flex sm:w-auto sm:gap-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => onChange(tab)}
            aria-current={active === tab ? "page" : undefined}
            className={cn(
              // 40px tall on phones for thumbs, a little tighter on desktop.
              "h-10 flex-1 shrink-0 rounded-full px-2 text-[13px] font-medium transition-colors sm:h-9 sm:flex-none sm:px-4 sm:text-sm",
              active === tab
                ? "bg-accent text-white shadow-sm"
                : "text-ink-muted hover:bg-surface-secondary hover:text-ink-primary"
            )}
          >
            {tab}
          </button>
        ))}
      </div>
    </nav>
  );
}
