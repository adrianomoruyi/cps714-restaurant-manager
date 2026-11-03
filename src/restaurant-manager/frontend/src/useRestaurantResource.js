import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';

export function useRestaurantResource(path, auth, onLogout) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError('');
    api(path, { credentials: auth.credentials, signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(error => {
        if (controller.signal.aborted) return;
        if (error.status === 401 || error.status === 403) onLogout(error.message);
        else setLoadError(error.message);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, auth, onLogout, revision]);

  async function save(path, method, body) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api(path, {
        method, credentials: auth.credentials,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      setNotice(result.message);
      refresh();
      return true;
    } catch (error) {
      if (error.status === 401) onLogout(error.message);
      else setError(error.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { data, loading, loadError, refresh, busy, error, notice, save };
}
