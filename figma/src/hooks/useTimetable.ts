// React Hooks for Timetable API
// Connects Figma frontend to existing backend timetable endpoints

import { useState, useEffect, useCallback } from 'react';
import type {
  TimetableEntry,
  Timetable,
} from '@/types/backend';
import {
  fetchTimetable,
  fetchTimetableEntries,
  createTimetableEntry,
  updateTimetableEntry,
  deleteTimetableEntry,
  importTimetableFromExcel,
} from '@/services/api';

// ============================================
// Timetable Data Hooks
// ============================================

export function useTimetable(pollInterval = 30000) {
  const [data, setData] = useState<Timetable | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchTimetable();
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

export function useTimetableEntries(personId?: string, pollInterval = 30000) {
  const [data, setData] = useState<TimetableEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchTimetableEntries(personId);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [personId]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}

export function useCreateTimetableEntry() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (entry: Omit<TimetableEntry, 'entry_id' | 'created_at' | 'updated_at'>) => {
    try {
      setLoading(true);
      setError(null);
      const result = await createTimetableEntry(entry);
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

export function useUpdateTimetableEntry() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (entryId: string, entry: Partial<TimetableEntry>) => {
    try {
      setLoading(true);
      setError(null);
      const result = await updateTimetableEntry(entryId, entry);
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

export function useDeleteTimetableEntry() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (entryId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await deleteTimetableEntry(entryId);
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

export function useImportTimetableFromExcel() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (file: File) => {
    try {
      setLoading(true);
      setError(null);
      const result = await importTimetableFromExcel(file);
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