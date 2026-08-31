// React Hooks for Replay API
// Connects Figma frontend to existing backend attendance endpoints for replay data

import { useState, useEffect, useCallback } from 'react';
import type {
  AttendanceRecord,
  AttendanceQueryParams,
  AttendanceQueryResult,
} from '@/types/backend';
import {
  fetchAttendanceRecords,
  fetchPersonAttendance,
} from '@/services/api';

// ============================================
// Replay Data Hooks
// ============================================

export function useReplayAppearances(params: AttendanceQueryParams = {}, pollInterval = 30000) {
  const [data, setData] = useState<AttendanceQueryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchAttendanceRecords(params);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}

export function usePersonReplayAppearances(personId: string, params: AttendanceQueryParams = {}, pollInterval = 30000) {
  const [data, setData] = useState<AttendanceQueryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!personId) return;
    try {
      setLoading(true);
      const result = await fetchPersonAttendance(personId, params);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [personId, params]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}