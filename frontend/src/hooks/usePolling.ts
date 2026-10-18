import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch now, then every `intervalMs` while `shouldContinue(data)` is true. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  shouldContinue: (data: T) => boolean,
  intervalMs = 1000,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const fetcherRef = useRef(fetcher);
  const continueRef = useRef(shouldContinue);
  fetcherRef.current = fetcher;
  continueRef.current = shouldContinue;

  const tick = useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
      if (continueRef.current(d)) timer.current = window.setTimeout(tick, intervalMs);
    } catch (e) {
      setError((e as Error).message);
      timer.current = window.setTimeout(tick, intervalMs * 3);
    }
  }, [intervalMs]);

  useEffect(() => {
    setData(null);
    tick();
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  /** Refetch immediately (and resume polling if needed). */
  return { data, setData, error, refresh: tick };
}
