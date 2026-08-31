// React Hooks for Parent/Telegram API
// Connects Figma frontend to existing backend parent/telegram endpoints

import { useState, useEffect, useCallback } from 'react';
import type {
  Parent,
  NotificationQueueStats,
} from '@/types/backend';
import {
  fetchParents,
  fetchParent,
  createParent,
  updateParent,
  linkParentTelegram,
  fetchNotificationQueueStats,
} from '@/services/api';

// ============================================
// Parent Data Hooks
// ============================================

export function useParents(pollInterval = 30000) {
  const [data, setData] = useState<Parent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchParents();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}

export function useParent(parentId: string) {
  const [data, setData] = useState<Parent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!parentId) return;
    try {
      setLoading(true);
      const result = await fetchParent(parentId);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [parentId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}

export function useCreateParent() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (parent: Omit<Parent, 'parent_id' | 'created_at'>) => {
    try {
      setLoading(true);
      setError(null);
      const result = await createParent(parent);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { mutate, loading, error };
}

export function useUpdateParent() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (parentId: string, parent: Partial<Parent>) => {
    try {
      setLoading(true);
      setError(null);
      const result = await updateParent(parentId, parent);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { mutate, loading, error };
}

export function useLinkParentTelegram() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (parentId: string, linkCode: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await linkParentTelegram(parentId, linkCode);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { mutate, loading, error };
}

export function useNotificationQueueStats(pollInterval = 10000) {
  const [data, setData] = useState<NotificationQueueStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchNotificationQueueStats();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}