import { useEffect, useState } from 'react';

/** The current time, refreshed every 30 seconds, so "2 h ago" and the scan status stay true. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  return now;
}
