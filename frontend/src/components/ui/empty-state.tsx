export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-dashed border-black/10 px-3 py-4 text-center text-sm text-zinc-500 dark:border-white/10 dark:text-zinc-500">
      {children}
    </p>
  );
}

export function LoadingState({ children = "Loading…" }: { children?: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 px-1 py-2 text-sm text-zinc-500 dark:text-zinc-500">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-700 dark:border-t-zinc-300" />
      {children}
    </p>
  );
}
