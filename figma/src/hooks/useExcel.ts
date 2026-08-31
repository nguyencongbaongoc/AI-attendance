// React Hooks for Excel Export API
// Connects Figma frontend to existing backend excel endpoints

import { useState, useEffect, useCallback } from 'react';
import type {
  DailyExportRequest,
  DailyExportResult,
} from '@/types/backend';
import {
  exportDailyAttendance,
  downloadExcelExport,
  listExcelExports,
} from '@/services/api';

// ============================================
// Excel Export Hooks
// ============================================

export function useExportDailyAttendance() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (request: DailyExportRequest) => {
    try {
      setLoading(true);
      setError(null);
      const result = await exportDailyAttendance(request);
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

export function useDownloadExcelExport() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (exportId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await downloadExcelExport(exportId);
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

export function useListExcelExports(pollInterval = 30000) {
  const [data, setData] = useState<DailyExportResult[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await listExcelExports();
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