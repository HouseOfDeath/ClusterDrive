import { useCallback, useEffect, useState } from 'react';

export default function useApiResource(loader) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    loader({ signal: controller.signal })
      .then((result) => setData(result))
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setError(requestError);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [loader, attempt]);

  const retry = useCallback(() => setAttempt((current) => current + 1), []);
  return { data, error, loading, retry };
}
