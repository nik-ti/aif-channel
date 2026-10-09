// Mirrors the Pydantic models in dashboard-backend/models/schemas.py.
// Kept in one file so a backend field rename is a one-place fix here.

export type ItemStatus = string;

export interface PostItem {
  id: number;
  time: string | null;
  source_name: string;
  title: string;
  body: string;
  url: string;
  story_id: number | null;
  status: ItemStatus;
  status_reason: string;
  importance: number;
  market: string;
  // The kind from the labeler (new_model, feature, tool...). Older items carry the
  // pre-2026-10-09 kinds (launch, resource).
  topic: string;
  company: string;
  // Why the sorter scored it as it did — the answer to "why did we cover this
  // at all", which status_reason only ever kept for items it REJECTED.
  sorter_reason: string;
  // Set only once a post exists and was sent. The link is built by the backend,
  // which is the only side that knows the channel's @name.
  telegram_message_id: number | null;
  telegram_url: string | null;
  // The editor's own verdict on the finished post. For a published item this is
  // the only place that says WHY it was allowed out — status_reason just says
  // "sent as message N".
  editor_verdict: "approve" | "decline" | null;
  editor_reason: string | null;
  editor_confidence: number | null;
  editor_attempt: number | null;
}

export interface PostsResponse {
  ready: boolean;
  items: PostItem[];
  total: number;
  limit: number;
  offset: number;
  // Per-status counts for the current source + keyword filter, ignoring the
  // status filter itself — the numbers on the status chips.
  status_counts: Record<string, number>;
}

export interface PostFilters {
  source: string | null;
  company: string | null;
  kind: string | null;
  statuses: string[];
  q: string;
}

export interface CompanyToday {
  company: string;
  posts_today: number;
  waiting: number;
}

export interface WaitingItem {
  id: number;
  title: string;
  company: string;
  kind: string;
  importance: number;
  time: string | null;
  status_reason: string;
}

export interface DigestPost {
  id: number;
  item_id: number;
  sent_at: string | null;
  company: string;
  text: string;
  telegram_url: string | null;
  items: { id: number; title: string }[];
}

export interface CompaniesResponse {
  ready: boolean;
  limit: number;
  digest_hour_utc: number;
  today: CompanyToday[];
  waiting: WaitingItem[];
  digests: DigestPost[];
}

export interface SourceCount {
  source_name: string;
  count: number;
}

export interface GateOutcomes {
  published: number;
  rejected: number;
  held: number;
  expired: number;
}

export interface TrendPoint {
  hour: string;
  count: number;
}

export type StatsRange = "24h" | "7d" | "30d" | "all";

export interface WindowTotals {
  ingested: number;
  published: number;
}

export interface StatsSummary extends WindowTotals {
  previous: WindowTotals | null;
  publish_rate: number | null;
  median_minutes_to_publish: number | null;
  queued_now: number;
  held_now: number;
  waiting_digest_now: number;
  last_published_at: string | null;
}

export interface ActivityPoint {
  bucket: string;
  ingested: number;
  published: number;
}

export interface StatusCount {
  status: string;
  count: number;
}

export interface SourcePerformance {
  source_name: string;
  total: number;
  published: number;
  folded: number;
  duplicate: number;
  filtered: number;
  avg_importance: number | null;
}

export interface StatsResponse {
  ready: boolean;
  range: StatsRange;
  sources_count: SourceCount[];
  gate_outcomes: GateOutcomes;
  trends: TrendPoint[];
  summary: StatsSummary | null;
  activity: ActivityPoint[];
  status_breakdown: StatusCount[];
  sources: SourcePerformance[];
  importance: { importance: number; count: number; published: number }[];
  markets: { market: string; count: number; published: number }[];
  kinds: { kind: string; count: number; published: number }[];
  companies: { company: string; count: number; published: number }[];
  editor: { approve: number; decline: number; top_rules: { rule: string; count: number }[] };
  dedup: { rung: string; dropped: number; kept: number }[];
  hour_of_day: { hour: number; count: number }[];
}

export interface GraphNode {
  id: string;
  label: string;
  description: string;
  last_invocation: string | null;
  error_count: number;
  health: "ok" | "degraded" | "error";
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphResponse {
  ready: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  // LangGraph's own drawing of the running graph (Mermaid, top to bottom).
  mermaid: string;
}

export interface NodeInfo {
  id: string;
  label: string;
  description: string;
  model: string;
  fallback_model: string | null;
  prompt: string | null;
}

export interface NodesResponse {
  ready: boolean;
  nodes: NodeInfo[];
}
