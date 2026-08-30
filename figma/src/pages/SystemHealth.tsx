// System Health Page - Migrated from existing frontend's SystemHealthPanel
// Now uses real backend data via hooks and store

import { useHealthStore } from '@/store';
import { useSystemHealth, useCameraHealth, useGPUStatus, useMetrics, useQueueMetrics, useQueueAlerts, useHealthRealtime } from '@/hooks/useHealth';
import type { SystemHealthResponse, CameraHealthResponse, GPUStatusResponse, MetricsResponse, AlertResponse } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, StatusDot, ConfidenceBar } from '@/components/ui/DesignSystem';

export default function SystemHealth() {
  const { data: systemHealth, loading: healthLoading, error: healthError } = useSystemHealth();
  const { data: cameraHealth, loading: cameraLoading } = useCameraHealth();
  const { data: gpuStatus, loading: gpuLoading } = useGPUStatus();
  const { data: metrics, loading: metricsLoading } = useMetrics();
  const { data: queueMetrics, loading: queueLoading } = useQueueMetrics();
  const { data: queueAlerts, loading: alertsLoading } = useQueueAlerts();
  const { connected, snapshot } = useHealthRealtime();
  const { systemHealth: storedHealth, cameraHealth: storedCameraHealth, gpuStatus: storedGPU, metrics: storedMetrics } = useHealthStore();

  // Use realtime data if available, otherwise fall back to polled data
  const health = snapshot?.type === 'health_update' ? {
    timestamp: snapshot.timestamp,
    overall_status: snapshot.overall_status,
    components: snapshot.components,
    cameras: snapshot.cameras,
    gpu: snapshot.gpu,
    runtime: snapshot.runtime,
  } : (systemHealth || storedHealth);

  const cameras = snapshot?.type === 'health_update' ? snapshot.cameras : (cameraHealth || storedCameraHealth);
  const gpu = snapshot?.type === 'health_update' ? snapshot.gpu : (gpuStatus || storedGPU);
  const metricsData = metrics || storedMetrics;

  const overallStatus = health?.overall_status ?? 'unknown';
  const isHealthy = overallStatus === 'healthy';
  const isDegraded = overallStatus === 'degraded';
  const isUnhealthy = overallStatus === 'unhealthy';

  const healthyCameras = cameras ? Object.values(cameras).filter(c => c.state === 'live').length : 0;
  const totalCameras = cameras ? Object.keys(cameras).length : 0;

  const gpuHealthy = gpu?.torch_cuda_available && gpu?.cuda_ep_registered;

  return (
    <div className="flex h-full flex-col gap-3 p-3 fade-in">
      {/* Header */}
      <div className="glass-elevated rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-base font-semibold text-white/90">System Health</div>
          <div className="text-white/40 text-sm mt-0.5">Real-time system monitoring and diagnostics</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <StatusDot status={connected ? "live" : "offline"} />
            <span className="font-mono text-[10px] text-white/35 uppercase tracking-wider">
              {connected ? "Real-time Connected" : "Real-time Disconnected"}
            </span>
          </div>
          <div className="w-px h-4 bg-white/8" />
          <div className={`glass-elevated flex flex-col items-center px-4 py-2 rounded-xl border ${isHealthy ? "bg-emerald-500/8 border-emerald-500/15" : isDegraded ? "bg-amber-500/8 border-amber-500/15" : "bg-rose-500/8 border-rose-500/15"}`}>
            <span className={`font-mono text-xl font-bold ${isHealthy ? "text-emerald-400" : isDegraded ? "text-amber-400" : "text-rose-400"}`}>{overallStatus.toUpperCase()}</span>
            <span className="font-mono text-[9px] text-white/30 uppercase tracking-[0.15em] mt-0.5">Overall</span>
          </div>
        </div>
      </div>

      {/* System Overview Grid */}
      <div className="grid grid-cols-4 gap-3">
        <div className="glass-elevated rounded-xl p-4">
          <SectionTitle>Cameras</SectionTitle>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <MonoLabel>Healthy</MonoLabel>
              <MonoValue className="text-emerald-400">{healthyCameras} / {totalCameras}</MonoValue>
            </div>
            {cameras && Object.entries(cameras).map(([id, cam]) => (
              <div key={id} className="flex items-center justify-between text-sm">
                <span className="font-mono text-white/70">{id}</span>
                <Badge type={cam.state} />
              </div>
            ))}
          </div>
        </div>

        <div className="glass-elevated rounded-xl p-4">
          <SectionTitle>GPU Status</SectionTitle>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <MonoLabel>CUDA</MonoLabel>
              <Badge type={gpu?.torch_cuda_available ? "verified" : "flagged"} />
            </div>
            <div className="flex items-center justify-between">
              <MonoLabel>ONNX Runtime CUDA EP</MonoLabel>
              <Badge type={gpu?.cuda_ep_registered ? "verified" : "flagged"} />
            </div>
            <div className="flex items-center justify-between">
              <MonoLabel>NVDEC</MonoLabel>
              <Badge type={gpu?.nvdec_available ? "verified" : "flagged"} />
            </div>
            <div className="flex items-center justify-between">
              <MonoLabel>GPU</MonoLabel>
              <MonoValue className="text-[11px] truncate max-w-[150px]">{gpu?.gpu_name ?? "Unknown"}</MonoValue>
            </div>
            <div className="flex items-center justify-between">
              <MonoLabel>Driver</MonoLabel>
              <MonoValue className="text-[11px]">{gpu?.driver_version ?? "Unknown"}</MonoValue>
            </div>
            <div className="flex items-center justify-between">
              <MonoLabel>CUDA Runtime</MonoLabel>
              <MonoValue className="text-[11px]">{gpu?.cuda_runtime_version ?? "Unknown"}</MonoValue>
            </div>
          </div>
        </div>

        <div className="glass-elevated rounded-xl p-4">
          <SectionTitle>Queue Metrics</SectionTitle>
          <div className="space-y-2">
            {queueMetrics && (
              <>
                <div className="flex items-center justify-between">
                  <MonoLabel>Pending</MonoLabel>
                  <MonoValue className="text-amber-400">{queueMetrics.total_pending}</MonoValue>
                </div>
                <div className="flex items-center justify-between">
                  <MonoLabel>Sent</MonoLabel>
                  <MonoValue className="text-emerald-400">{queueMetrics.total_sent}</MonoValue>
                </div>
                <div className="flex items-center justify-between">
                  <MonoLabel>Failed</MonoLabel>
                  <MonoValue className="text-rose-400">{queueMetrics.total_failed}</MonoValue>
                </div>
                <div className="flex items-center justify-between">
                  <MonoLabel>Utilization</MonoLabel>
                  <MonoValue>{queueMetrics.queue_utilization_percent?.toFixed(1) ?? "0"}%</MonoValue>
                </div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden mt-2">
                  <div className="h-full bg-amber-400 rounded-full" style={{ width: `${queueMetrics.queue_utilization_percent ?? 0}%` }} />
                </div>
              </>
            )}
          </div>
        </div>

        <div className="glass-elevated rounded-xl p-4">
          <SectionTitle>Alerts</SectionTitle>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {queueAlerts && queueAlerts.length > 0 ? (
              queueAlerts.map((alert, i) => (
                <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-white/3 border border-white/5">
                  <Badge type={alert.severity === 'critical' ? 'flagged' : alert.severity === 'warning' ? 'pending' : 'verified'} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white/80 font-medium truncate">{alert.message}</div>
                    <div className="text-[10px] text-white/40">{alert.metric}: {alert.value} (threshold: {alert.threshold})</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center text-white/30 py-8 text-sm">No active alerts</div>
            )}
          </div>
        </div>
      </div>

      {/* Detailed Components */}
      <div className="grid grid-cols-2 gap-3">
        {/* Component Health */}
        <div className="glass-elevated rounded-xl p-4 flex-1 flex flex-col">
          <SectionTitle>Component Health</SectionTitle>
          <div className="flex-1 overflow-y-auto space-y-2">
            {health?.components?.map((comp, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-white/3 border border-white/5">
                <div className="flex items-center gap-2">
                  <StatusDot status={comp.status} />
                  <MonoLabel className="text-sm">{comp.component}</MonoLabel>
                </div>
                <Badge type={comp.status} />
              </div>
            ))}
          </div>
        </div>

        {/* Camera Details */}
        <div className="glass-elevated rounded-xl p-4 flex-1 flex flex-col">
          <SectionTitle>Camera Details</SectionTitle>
          <div className="flex-1 overflow-y-auto space-y-2">
            {cameras && Object.entries(cameras).map(([id, cam]) => (
              <div key={id} className="glass rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-white/80">{id}</span>
                  <Badge type={cam.state} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  <div><MonoLabel>Frames Rx</MonoLabel><MonoValue>{cam.frames_received.toLocaleString()}</MonoValue></div>
                  <div><MonoLabel>Frames Dropped</MonoLabel><MonoValue>{cam.frames_dropped}</MonoValue></div>
                  <div><MonoLabel>Errors</MonoLabel><MonoValue>{cam.total_errors}</MonoValue></div>
                  <div><MonoLabel>Uptime</MonoLabel><MonoValue>{Math.round(cam.uptime_seconds / 60)}m</MonoValue></div>
                  <div><MonoLabel>FPS</MonoLabel><MonoValue>{cam.current_fps ?? "—"}</MonoValue></div>
                  <div><MonoLabel>Resolution</MonoLabel><MonoValue>{cam.current_resolution ? `${cam.current_resolution[0]}x${cam.current_resolution[1]}` : "—"}</MonoValue></div>
                  <div><MonoLabel>Codec</MonoLabel><MonoValue>{cam.current_codec ?? "—"}</MonoValue></div>
                  <div><MonoLabel>Reconnects</MonoLabel><MonoValue>{cam.reconnect_count}</MonoValue></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* GPU Model Availability */}
      {gpu?.model_availability && Object.keys(gpu.model_availability).length > 0 && (
        <div className="glass-elevated rounded-xl p-4">
          <SectionTitle>Model Availability</SectionTitle>
          <div className="grid grid-cols-3 gap-3">
            {Object.entries(gpu.model_availability).map(([model, status]) => (
              <div key={model} className="glass rounded-lg p-3">
                <div className="font-mono text-[11px] text-white/70 truncate">{model}</div>
                <Badge type={status === 'available' ? 'verified' : status === 'loading' ? 'pending' : 'flagged'} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runtime Info */}
      <div className="glass-elevated rounded-xl p-4">
        <SectionTitle>Runtime</SectionTitle>
        <div className="grid grid-cols-4 gap-4">
          {health?.runtime && (
            <>
              <div><MonoLabel>Python</MonoLabel><MonoValue>{health.runtime.python_version}</MonoValue></div>
              <div><MonoLabel>Platform</MonoLabel><MonoValue>{health.runtime.platform}</MonoValue></div>
              <div><MonoLabel>Architecture</MonoLabel><MonoValue>{health.runtime.architecture}</MonoValue></div>
              <div><MonoLabel>Venv</MonoLabel><MonoValue>{health.runtime.venv_active ? 'Active' : 'Inactive'}</MonoValue></div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}