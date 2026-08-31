// React Hooks for Persons API
// Connects Figma frontend to existing backend persons endpoints

import { useState, useEffect, useCallback } from 'react';
import type {
  Person,
  PersonSearchParams,
  PersonSearchResult,
  EnrollmentPerson,
  EnrollmentStats,
  QualityCheckResult,
  AttendanceQueryResult,
} from '@/types/backend';
import {
  fetchPersons,
  fetchPerson,
  fetchPersonAppearanceHistory,
  fetchEnrolledPersons,
  fetchEnrollmentStats,
  enrollPerson,
  deleteEnrolledPerson,
  runQualityCheck,
} from '@/services/api';

// ============================================
// Persons Data Hooks
// ============================================

export function usePersons(params: PersonSearchParams = {}, pollInterval = 10000) {
  const [data, setData] = useState<PersonSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchPersons(params);
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

export function usePerson(personId: string) {
  const [data, setData] = useState<Person | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!personId) return;
    try {
      setLoading(true);
      const result = await fetchPerson(personId);
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
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}

export function usePersonAppearanceHistory(personId: string, pollInterval = 10000) {
  const [data, setData] = useState<AttendanceQueryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!personId) return;
    try {
      setLoading(true);
      const result = await fetchPersonAppearanceHistory(personId);
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

// ============================================
// Enrollment Hooks
// ============================================

export function useEnrolledPersons(pollInterval = 30000) {
  const [data, setData] = useState<EnrollmentPerson[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchEnrolledPersons();
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

export function useEnrollmentStats(pollInterval = 30000) {
  const [data, setData] = useState<EnrollmentStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchEnrollmentStats();
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

export function useEnrollPerson() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (data: {
    person_id: string;
    name: string;
    role: 'student' | 'staff' | 'visitor';
    face_embedding: number[];
    face_quality: number;
  }) => {
    try {
      setLoading(true);
      setError(null);
      const result = await enrollPerson(data);
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

export function useDeleteEnrolledPerson() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (personId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await deleteEnrolledPerson(personId);
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

export function useRunQualityCheck() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (personId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await runQualityCheck(personId);
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