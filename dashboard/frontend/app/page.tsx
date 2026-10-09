// Main layout: header, tab nav, the active tab's content, and the global
// "API offline" banner driven by a lightweight health-check poll.
//
// The open tab lives in the URL (?tab=stats), so a reload stays where you were.
// Reading it needs next/navigation's useSearchParams, which Next.js requires
// to sit under a Suspense boundary even in an all-client page — hence the
// HomeContent/Home split below.
"use client";

import { Suspense, useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { CompaniesView } from "@/components/CompaniesView";
import { GraphViewer } from "@/components/GraphViewer";
import { Header } from "@/components/Header";
import { NodesViewer } from "@/components/NodesViewer";
import { PostsFeed } from "@/components/PostsFeed";
import { StatsPanel } from "@/components/StatsPanel";

import { TabNav, TABS, type Tab } from "@/components/TabNav";
import { Button } from "@/components/ui/button";
import { useHealth } from "@/hooks/useApi";
import { cn } from "@/lib/utils";

const TAB_CONTENT: Record<Tab, React.ComponentType> = {
  Posts: PostsFeed,
  Companies: CompaniesView,
  Stats: StatsPanel,
  Graph: GraphViewer,
  Nodes: NodesViewer,
};

function HomeContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: Tab = TABS.find((t) => t.toLowerCase() === tabParam) ?? TABS[0];

  const replaceParams = useCallback(
    (params: URLSearchParams) => {
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  const setTab = useCallback(
    (next: Tab) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === TABS[0]) params.delete("tab");
      else params.set("tab", next.toLowerCase());
      replaceParams(params);
    },
    [searchParams, replaceParams]
  );

  const health = useHealth();
  const offline = health.isError;

  const ActiveTab = TAB_CONTENT[tab];

  return (
    <div className="min-h-screen bg-surface-secondary">
      <Header />

      {offline && (
        <div className="flex items-center justify-between gap-3 bg-status-rejected/10 px-4 py-2 text-sm text-status-rejected">
          <span>API offline — showing last known data.{health.isFetching ? " Retrying..." : ""}</span>
          <Button variant="outline" size="sm" onClick={() => health.refetch()}>
            Retry
          </Button>
        </div>
      )}

      <TabNav active={tab} onChange={setTab} />

      <main className={cn("transition-opacity", offline && "pointer-events-none opacity-50")}>
        <ActiveTab />
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-surface-secondary" />}>
      <HomeContent />
    </Suspense>
  );
}
