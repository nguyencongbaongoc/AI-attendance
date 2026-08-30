// React Hooks for Health Monitoring API
// Connects Figma frontend to existing backend health endpoints

import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  SystemHealthResponse,
  CameraHealthResponse,
  GPUStatusResponse,
  MetricsResponse,
  QueueMetricsResponse,
  AlertResponse,
  HealthSnapshot,
  ConnectionStats,
} from '@/types/backend';
import {
  fetchSystemHealth,
  fetchCameraHealth,
  fetchCameraHealthById,
  fetchGPUStatus,
  fetchMetrics,
  fetchQueueMetrics,
  fetchQueueAlerts,
  fetchQueueStats,
  fetchHealthSnapshot,
  fetchConnectionStats,
  healthWS,
  healthSSE,
  HealthWebSocketHandler,
} from '@/services/api';

// ============================================
// Health Data Hooks
// ============================================

export function useSystemHealth(pollInterval = 10000) {
  const [data, setData] = useState<SystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchSystemHealth();
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

export function useCameraHealth(pollInterval = 10000) {
  const [data, setData] = useState<Record<string, CameraHealthResponse> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchCameraHealth();
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

export function useCameraHealthById(cameraId: string, pollInterval = 10000) {
  const [data, setData] = useState<CameraHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!cameraId) return;
    try {
      setLoading(true);
      const result = await fetchCameraHealthById(cameraId);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [cameraId]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, pollInterval);
    return () => clearInterval(interval);
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}

export function useGPUStatus(pollInterval = 30000) {
  const [data, setData] = useState<GPUStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchGPUStatus();
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

export function useMetrics(pollInterval = 10000) {
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchMetrics();
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

export function useQueueMetrics(pollInterval = 10000) {
  const [data, setData] = useState<QueueMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchQueueMetrics();
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

export function useQueueAlerts(pollInterval = 10000) {
  const [data, setData] = useState<AlertResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchQueueAlerts();
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

export function useQueueStats(pollInterval = 10000) {
  const [data, setData] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchQueueStats();
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

// ============================================
// Real-time Health Hooks (WebSocket/SSE)
// ============================================

export function useHealthWebSocket() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Event | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [lastSeq, setLastSeq] = useState(0);
  const handlerRef = useRef<HealthWebSocketHandler | null>(null);

  useEffect(() => {
    handlerRef.current = (newSnapshot: HealthSnapshot) => {
      setSnapshot(newSnapshot);
      if (newSnapshot.seq !== undefined) {
        setLastSeq(newSnapshot.seq);
      }
      if (newSnapshot.connection_id) {
        setConnectionId(newSnapshot.connection_id);
      }
    };

    const unsubscribe = healthWS.onMessage(handlerRef.current);
    const unsubscribeError = healthWS.onError((err) => {
      setError(err);
      setConnected(false);
    });
    const unsubscribeClose = healthWS.onClose(() => {
      setConnected(false);
    });

    healthWS.connect();
    setConnected(healthWS.isConnected());

    return () => {
      unsubscribe();
      unsubscribeError();
      unsubscribeClose();
    };
  }, []);

  const requestSync = useCallback(() => {
    healthWS.requestSync();
  }, []);

  const acknowledge = useCallback((seq: number) => {
    healthWS.acknowledge(seq);
  }, []);

  const subscribe = useCallback((events: string[]) => {
    healthWS.subscribe(events);
  }, []);

  const disconnect = useCallback(() => {
    healthWS.disconnect();
    setConnected(false);
  }, []);

  return {
    snapshot,
    connected,
    error,
    connectionId,
    lastSeq,
    requestSync,
    acknowledge,
    subscribe,
    disconnect,
  };
}

export function useHealthSSE() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Event | null>(null);
  const handlerRef = useRef<HealthWebSocketHandler | null>(null);

  useEffect(() => {
    handlerRef.current = (newSnapshot: HealthSnapshot) => {
      setSnapshot(newSnapshot);
    };

    const unsubscribe = healthSSE.onMessage(handlerRef.current);
    const unsubscribeError = healthSSE.onError((err) => {
      setError(err);
      setConnected(false);
    });

    healthSSE.connect();
    setConnected(healthSSE.isConnected());

    return () => {
      unsubscribe();
      unsubscribeError();
    };
  }, []);

  const disconnect = useCallback(() => {
    healthSSE.disconnect();
    setConnected(false);
  }, []);

  return {
    snapshot,
    connected,
    error,
    disconnect,
  };
}

// Unified realtime hook - prefers WebSocket, falls back to SSE
export function useHealthRealtime(preferWebSocket = true) {
  const ws = useHealthWebSocket();
  const sse = useHealthSSE();

  // Use WebSocket if available and preferred, otherwise SSE
  const useWS = preferWebSocket && ws.connected;
  const active = useWS ? ws : sse;

  return {
    snapshot: active.snapshot,
    connected: active.connected,
    error: active.error,
    connectionId: 'connectionId' in active ? active.connectionId : null,
    lastSeq: 'lastSeq' in active ? active.lastSeq : 0,
    requestSync: 'requestSync' in active ? active.requestSync : undefined,
    acknowledge: 'acknowledge' in active ? active.acknowledge : undefined,
    subscribe: 'subscribe' in active ? active.subscribe : undefined,
    disconnect: active.disconnect,
  };
}

export function useConnectionStats(pollInterval = 30000) {
  const [data, setData] = useState<ConnectionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchConnectionStats();
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

// ============================================
// Derived/Computed Hooks
// ============================================

export function useHealthSummary() {
  const { data: systemHealth } = useSystemHealth();
  const { data: cameraHealth } = useCameraHealth();
  const { data: gpuStatus } = useGPUStatus();
  const { data: metrics } = useMetrics();

  const healthyCameras = cameraHealth
    ? Object.values(cameraHealth).filter(c => c.state === 'live').length
    : 0;
  const totalCameras = cameraHealth ? Object.keys(cameraHealth).length : 0;

  const gpuHealthy = gpuStatus?.torch_cuda_available && gpuStatus?.cuda_ep_registered;

  return {
    systemHealth,
    cameraHealth,
    gpuStatus,
    metrics,
    healthyCameras,
    totalCameras,
    gpuHealthy,
    overallStatus: systemHealth?.overall_status ?? 'unknown',
    isHealthy: systemHealth?.overall_status === 'healthy',
    isDegraded: systemHealth?.overall_status === 'degraded',
    isUnhealthy: systemHealth?.overall_status === 'unhealthy',
  };
}