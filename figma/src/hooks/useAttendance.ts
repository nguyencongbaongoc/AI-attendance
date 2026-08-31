// React Hooks for Attendance API
// Connects Figma frontend to existing backend attendance endpoints

import { useState, useEffect, useCallback } from 'react';
import type {
  AttendanceRecord,
  AttendanceSummary,
  AttendanceQueryParams,
  AttendanceQueryResult,
} from '@/types/backend';
import {
  fetchAttendanceSummary,
  fetchAttendanceRecords,
  fetchAttendanceRecord,
  fetchPersonAttendance,
} from '@/services/api';

// ============================================
// Attendance Data Hooks
// ============================================

export function useAttendanceSummary(pollInterval = 10000) {
  const [data, setData] = useState<AttendanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchAttendanceSummary();
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

export function useAttendanceRecords(params: AttendanceQueryParams = {}, pollInterval = 10000) {
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

export function useAttendanceRecord(recordId: string) {
  const [data, setData] = useState<AttendanceRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!recordId) return;
    try {
      setLoading(true);
      const result = await fetchAttendanceRecord(recordId);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [recordId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}

export function usePersonAttendance(personId: string, params: AttendanceQueryParams = {}, pollInterval = 10000) {
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