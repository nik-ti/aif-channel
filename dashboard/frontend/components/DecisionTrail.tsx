// "What happened" for one item: who looked at it, in order, and what each one
// decided. Replaces three loose "Why" lines that never said whose reason was whose.
// Steps: 1 the sorter (worth covering?), 2 the editor (is the post right?),
// 3 the outcome — skipping any text an earlier step already showed.
import { StatusReason } from "@/components/StatusReason";
import { COPY } from "@/lib/copy";
import { statusInfo } from "@/lib/status";
import { cn } from "@/lib/utils";

export interface TrailItem {
  status: string;
  status_reason: string;
  sorter_reason: string;
  importance?: number;
  market?: string;
  editor_verdict: "approve" | "decline" | null;
  editor_reason: string | null;
  editor_confidence: number | null;
  editor_attempt?: number | null;
}

// Statuses the sorter itself decided; nothing happened after it.
const STOPPED_BY_SORTER = new Set(["irrelevant", "low_impact"]);

function Step({
  n,
  who,
  verdict,
  tone,
  children,
}: {
  n: number;
  who: string;
  verdict: string;
  tone: "good" | "bad" | "neutral";
  children?: React.ReactNode;
}) {
  return (
    <li className="flex gap-2.5">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-secondary text-[11px] font-semibold text-ink-primary">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs">
          <span className="font-semibold text-ink-primary">{who}</span>{" "}
          <span
            className={cn(
              "font-medium",
              tone === "good" && "text-emerald-700 dark:text-emerald-400",
              tone === "bad" && "text-rose-700 dark:text-rose-400",
              tone === "neutral" && "text-ink-muted"
            )}
          >
            {verdict}
          </span>
        </p>
        {children && <div className="mt-0.5 text-xs leading-relaxed text-ink-muted">{children}</div>}
      </div>
    </li>
  );
}

function outcomeVerdict(status: string): string {
  switch (status) {
    case "published":
      return "sent it to the channel";
    case "declined":
      return "not posted — the editor's rejection was final";
    case "held":
      return "not sent — the finished post repeated a recent one";
    case "waiting_digest":
      return "waiting for its company's evening digest";
    case "merged":
      return "went out as a line in a company digest";
    case "queued":
    case "written":
      return "still in progress";
    default:
      return statusInfo(status).label.toLowerCase() || status;
  }
}

export function DecisionTrail({ item }: { item: TrailItem }) {
  const copy = COPY;
  const steps: React.ReactNode[] = [];
  const stoppedEarly = STOPPED_BY_SORTER.has(item.status);

  if (item.sorter_reason) {
    const facts = [
      item.importance ? `${copy.importance} ${item.importance}/5` : "",
      item.market && item.market !== "none" ? `${copy.marketShort} ${item.market}` : "",
    ].filter(Boolean);
    steps.push(
      <Step
        key="sorter"
        n={steps.length + 1}
        who="Sorter"
        verdict={stoppedEarly ? "stopped it" : "let it through"}
        tone={stoppedEarly ? "bad" : "good"}
      >
        {facts.length > 0 && <span className="text-ink-primary">{facts.join(" · ")}. </span>}
        {item.sorter_reason}
      </Step>
    );
  }

  if (item.editor_verdict && item.editor_reason) {
    const details = [
      item.editor_confidence != null ? `${Math.round(item.editor_confidence * 100)}% sure` : "",
      item.editor_attempt != null && item.editor_attempt > 1 ? "on the rewritten draft" : "",
    ].filter(Boolean);
    steps.push(
      <Step
        key="editor"
        n={steps.length + 1}
        who="Editor"
        verdict={item.editor_verdict === "approve" ? "approved the post" : "rejected the post"}
        tone={item.editor_verdict === "approve" ? "good" : "bad"}
      >
        {details.length > 0 && <span className="text-ink-primary">{details.join(" · ")}. </span>}
        {item.editor_reason}
      </Step>
    );
  }

  if (!stoppedEarly) {
    // The outcome's own reason, unless it only repeats what a step above said.
    const reason = item.status_reason || "";
    const repeats =
      reason.startsWith("sent as message") ||
      reason.startsWith("editor rejected it") ||
      (item.editor_reason && reason.includes(item.editor_reason)) ||
      (item.sorter_reason && reason.includes(item.sorter_reason));
    steps.push(
      <Step
        key="outcome"
        n={steps.length + 1}
        who="Outcome:"
        verdict={outcomeVerdict(item.status)}
        tone={item.status === "published" ? "good" : item.status === "declined" ? "bad" : "neutral"}
      >
        {reason && !repeats ? <StatusReason reason={reason} /> : null}
      </Step>
    );
  } else if (item.status_reason && !item.status_reason.includes(item.sorter_reason)) {
    steps.push(
      <Step key="outcome" n={steps.length + 1} who="Outcome:" verdict={outcomeVerdict(item.status)} tone="neutral">
        <StatusReason reason={item.status_reason} />
      </Step>
    );
  }

  if (steps.length === 0) return null;
  return (
    <div className="rounded-md bg-surface-secondary/60 px-3 py-2.5">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">What happened</p>
      <ol className="flex flex-col gap-2">{steps}</ol>
    </div>
  );
}
