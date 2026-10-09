// Shown in place of a tab's content when the API says "ready": false — the
// channel has no database file yet. Calm and specific, not a red banner.

export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 glass-panel rounded-2xl px-6 py-14 text-center">
      <p className="text-sm font-medium text-ink-primary">No data yet for AI Flow</p>
      <p className="max-w-sm text-xs text-ink-muted">
        This channel doesn&apos;t have a database yet — its pipeline hasn&apos;t collected anything.
        Once it starts running, this tab fills in on its own.
      </p>
    </div>
  );
}
