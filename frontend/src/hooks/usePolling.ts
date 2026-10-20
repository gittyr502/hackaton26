import { useCallback, useEffect, useRef, useState } from "react";

/** While the live (SSE) stream is connected, polling is only a safety net. */
const SSE_FALLBACK_MS = 5000;

/** Fetch now, then every `intervalMs` while `shouldContinue(data)` is true.
 *
 * With `eventsUrl` (server-sent events), every `changed` event refetches at once, and while that stream
 * is connected polling slows to a fallback every SSE_FALLBACK_MS. If the stream drops, polling is back to normal.
 *
 * A response is dropped when it is older than what is on screen: a newer request already answered,
 * or the page changed the data itself (setData, e.g. a saved edit) after the request was sent.
 * Without this, a poll sent just before a save would put the old value back.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  shouldContinue: (data: T) => boolean,
  intervalMs = 1000,
  deps: unknown[] = [],
  eventsUrl: string | null = null,
) {
  const [data, setDataState] = useState<T | null>(null);
  const [live, setLive] = useState(false);
  const every = live ? Math.max(intervalMs, SSE_FALLBACK_MS) : intervalMs;
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const fetcherRef = useRef(fetcher);
  const continueRef = useRef(shouldContinue);
  const seq = useRef(0); // id of the latest request sent
  const applied = useRef(0); // id of the latest response shown
  const localEdit = useRef(0); // request id current when the page last changed the data itself
  fetcherRef.current = fetcher;
  continueRef.current = shouldContinue;

  const setData: typeof setDataState = useCallback((v) => {
    localEdit.current = seq.current;
    setDataState(v);
  }, []);

  const tick = useCallback(async () => {
    window.clearTimeout(timer.current);
    const mine = ++seq.current;
    try {
      const d = await fetcherRef.current();
      const stale = mine <= applied.current || mine <= localEdit.current;
      if (!stale) {
        applied.current = mine;
        setDataState(d);
        setError(null);
      }
      if (mine === seq.current) {
        if (stale) timer.current = window.setTimeout(tick, every);
        else if (continueRef.current(d)) timer.current = window.setTimeout(tick, every);
      }
    } catch (e) {
      if (mine === seq.current) {
        setError((e as Error).message);
        timer.current = window.setTimeout(tick, every * 3);
      }
    }
  }, [every]);

  const tickRef = useRef(tick);
  tickRef.current = tick;

  // Live updates: refetch on every change the server announces.
  useEffect(() => {
    if (!eventsUrl || typeof EventSource === "undefined") return;
    const source = new EventSource(eventsUrl);
    source.addEventListener("changed", () => {
      setLive(true);
      tickRef.current();
    });
    source.onerror = () => setLive(false); // the browser retries by itself; poll normally meanwhile
    return () => {
      source.close();
      setLive(false);
    };
  }, [eventsUrl]);

  useEffect(() => {
    setDataState(null);
    tick();
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  /** Refetch immediately (and resume polling if needed). */
  return { data, setData, error, refresh: tick };
}
