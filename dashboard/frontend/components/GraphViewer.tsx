// Graph tab: the pipeline as LangGraph itself draws it (top to bottom, dotted lines for
// the routes an item can take), shrunk to a preview until you expand it, plus the
// workflow write-up underneath. A station that is failing is tinted amber or red; click
// one to see its numbers. Mermaid only runs in the browser (it touches `document`), so
// it's imported inside an effect.
"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { EmptyState } from "@/components/EmptyState";
import { useGraph } from "@/hooks/useApi";
import type { GraphNode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { WORKFLOW_EXPLANATION } from "@/lib/workflowExplanation";

const EXPANDED_KEY = "aif-graph-expanded";

function formatTime(iso: string | null) {
  if (!iso) return "never";
  const date = new Date((iso.includes("T") ? iso : iso.replace(" ", "T")) + "Z");
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// LangGraph's diagram, plus a click handler on every station and a tint on the
// unhealthy ones. Its own colours (lavender boxes) are kept as they are.
function buildDiagram(mermaid: string, nodes: GraphNode[]): string {
  const lines = [mermaid.trim()];
  for (const node of nodes) {
    lines.push(`\tclick ${node.id} call aifGraphNodeClick("${node.id}")`);
    if (node.health !== "ok") lines.push(`\tclass ${node.id} ${node.health}`);
  }
  lines.push("\tclassDef degraded fill:#FDE68A,stroke:#D97706");
  lines.push("\tclassDef error fill:#FCA5A5,stroke:#B91C1C");
  return lines.join("\n");
}

export function GraphViewer() {
  const { data, isFetching } = useGraph();
  const [selected, setSelected] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const nodes = data?.nodes ?? [];
  const mermaidSource = data?.mermaid ?? "";
  const selectedNode = nodes.find((n) => n.id === selected) ?? null;

  useEffect(() => {
    try {
      setExpanded(localStorage.getItem(EXPANDED_KEY) === "1");
    } catch {
      // Storage unavailable: start collapsed.
    }
  }, []);

  function toggleExpanded() {
    setExpanded((prev) => {
      try {
        localStorage.setItem(EXPANDED_KEY, prev ? "0" : "1");
      } catch {
        // Not remembered; fine.
      }
      return !prev;
    });
  }

  useEffect(() => {
    (window as unknown as Record<string, unknown>).aifGraphNodeClick = (id: string) => {
      setSelected((prev) => (prev === id ? null : id));
    };
    return () => {
      delete (window as unknown as Record<string, unknown>).aifGraphNodeClick;
    };
  }, []);

  useEffect(() => {
    if (!mermaidSource || !containerRef.current) return;
    let cancelled = false;

    import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "loose", theme: "base" });
      try {
        const { svg, bindFunctions } = await mermaid.render(
          `pipeline-graph-${Date.now()}`,
          buildDiagram(mermaidSource, nodes)
        );
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        bindFunctions?.(containerRef.current);
        setRenderError(null);
      } catch (err) {
        if (!cancelled) {
          setRenderError(err instanceof Error ? err.message : String(err));
        }
      }
    });

    return () => {
      cancelled = true;
    };
    // Re-render whenever node health/labels change (e.g. after a poll).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mermaidSource, JSON.stringify(nodes)]);

  const notReady = data ? !data.ready : false;

  return (
    <div className="flex flex-col gap-4 p-4">
      {isFetching && <span className="text-xs text-ink-muted">Refreshing...</span>}

      {notReady ? (
        <EmptyState />
      ) : (
        <>
          <div className="rounded-lg border border-border bg-surface-primary">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
              <p className="text-sm font-semibold text-ink-primary">The pipeline</p>
              <button
                type="button"
                onClick={toggleExpanded}
                aria-expanded={expanded}
                className="inline-flex h-11 items-center gap-1 rounded-md px-3 text-xs font-medium text-ink-primary hover:bg-surface-secondary sm:h-8"
              >
                {expanded ? (
                  <>
                    Collapse <ChevronUp className="h-4 w-4" />
                  </>
                ) : (
                  <>
                    Expand <ChevronDown className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
            {renderError ? (
              <p className="p-4 text-sm text-status-rejected">Diagram failed to render: {renderError}</p>
            ) : !mermaidSource ? (
              <p className="p-4 text-sm text-ink-muted">
                The diagram appears once the channel has restarted on this version.
              </p>
            ) : (
              <div className="relative">
                <div
                  className={cn("overflow-hidden px-4 py-3 transition-[max-height]", expanded ? "max-h-none" : "max-h-80")}
                >
                  <div
                    ref={containerRef}
                    className={cn(
                      "mx-auto flex justify-center [&_svg]:h-auto [&_svg]:max-w-full",
                      expanded ? "max-w-xl" : "max-w-md"
                    )}
                  />
                </div>
                {!expanded && (
                  <button
                    type="button"
                    onClick={toggleExpanded}
                    aria-label="Expand the pipeline diagram"
                    className="absolute inset-x-0 bottom-0 flex h-20 items-end justify-center bg-gradient-to-t from-surface-primary to-transparent pb-2 text-xs font-medium text-ink-muted"
                  >
                    Show the whole pipeline
                  </button>
                )}
              </div>
            )}
          </div>

          {selectedNode ? (
            <div className="rounded-lg border border-border bg-surface-primary p-4 text-sm">
              <p className="font-semibold text-ink-primary">{selectedNode.label}</p>
              {selectedNode.description && (
                <p className="text-ink-muted">{selectedNode.description}</p>
              )}
              <p className="text-ink-muted">Health: {selectedNode.health}</p>
              <p className="text-ink-muted">Last invocation: {formatTime(selectedNode.last_invocation)}</p>
              <p className="text-ink-muted">Error count: {selectedNode.error_count}</p>
            </div>
          ) : (
            <p className="text-xs text-ink-muted">Click a station in the diagram to see its numbers.</p>
          )}
        </>
      )}

      {/* The workflow write-up explains the shared machinery, not this
          database, so it stays visible even with no database yet. */}
      <div className="rounded-lg border border-border bg-surface-primary p-4 md:p-6">
        <article className="prose-workflow">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Markdown tables don't wrap themselves — without this a wide
              // table (the "Dashboard Summary" one) overflows at 375px. It
              // still overflows even wrapped (the content itself is wide),
              // so phones get a hint that there's more to the right.
              table: ({ ...props }) => (
                <div>
                  <p className="mb-1 text-xs text-ink-muted sm:hidden">Swipe to see the full table →</p>
                  <div className="table-scroll">
                    <table {...props} />
                  </div>
                </div>
              ),
            }}
          >
            {WORKFLOW_EXPLANATION}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
