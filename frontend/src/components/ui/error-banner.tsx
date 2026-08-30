import { ApiError } from "@/lib/api";

export function describeError(err: unknown): { code: string | null; message: string } {
  if (err instanceof ApiError) {
    return { code: err.code, message: err.message };
  }
  if (err instanceof Error) {
    return { code: null, message: err.message };
  }
  return { code: null, message: "Something went wrong." };
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { code, message } = describeError(error);
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
      <div>
        {code && <span className="mr-1.5 font-mono text-xs opacity-80">{code}</span>}
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 whitespace-nowrap rounded border border-rose-300 px-2 py-0.5 text-xs font-medium hover:bg-rose-100 dark:border-rose-800 dark:hover:bg-rose-900"
        >
          Retry
        </button>
      )}
    </div>
  );
}
