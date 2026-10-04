// Shared channel constants/helpers — kept separate from types.ts so both
// the URL-state hook in page.tsx and any tab component can import just this,
// without pulling in every response shape.

export const DEFAULT_CHANNEL = "markets";

// A human label built the same way the backend's channel_resolver falls
// back when a channel's own display name (from /channels) isn't loaded yet
// — e.g. "ai_news" -> "AI News". Used only until the real list arrives.
export function channelLabel(id: string): string {
  return id
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => (w.toLowerCase() === "ai" ? "AI" : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

// Words that differ by channel: the sorter scores "market impact" on Market One
// and "usefulness" on AI Flow, and its third answer is a market or an audience.
export function channelCopy(channel: string) {
  if (channel === "ai_news") {
    return { importance: "Usefulness", market: "Who can use it", marketShort: "for" };
  }
  return { importance: "Market impact", market: "Market", marketShort: "market:" };
}
