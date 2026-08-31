// Command Center Page - Live Dashboard
// Migrated from original Figma App.tsx CommandCenter component
// Now uses real backend data via hooks and store

import { useState, useEffect, useMemo } from 'react';
import { useHealthStore, useAttendanceStore, useUIStore } from '@/store';
import { useSystemHealth, useCameraHealth, useHealthSummary, useHealthRealtime } from '@/hooks/useHealth';
import { useAttendanceSummary, useAttendanceRecords } from '@/hooks/useAttendance';
import type { CameraHealthResponse, AttendanceRecord } from '@/types/backend';
import { Badge, StatusDot, ConfidenceBar, MonoLabel, MonoValue, SectionTitle, GlassButton } from '@/components/ui/DesignSystem';
import CameraCard from '@/components/dashboard/CameraCard';
import EventRow from '@/components/attendance/EventRow';

interface CommandCenterProps {
  onPersonClick: (id: string) => void;
}

export default function CommandCenter({ onPersonClick }: CommandCenterProps) {
  const [time, setTime] = useState(new Date());
  const [selectedCam, setSelectedCam] = useState<string | null>(null);

  const { data: systemHealth, loading: healthLoading } = useSystemHealth();
  const { data: cameraHealth, loading: cameraLoading } = useCameraHealth();
  const {
    healthyCameras,
    totalCameras,
    gpuHealthy,
    overallStatus,
    isHealthy,
    isDegraded,
    isUnhealthy
  } = useHealthSummary();

  const { data: attendanceSummary, loading: attendanceLoading } = useAttendanceSummary();
  const { data: attendanceRecords, loading: recordsLoading } = useAttendanceRecords({ limit: 20 });
  const { setLoadingState } = useUIStore();
  const { connected, requestSync, disconnect } = useHealthRealtime();

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    setLoadingState('cameras', cameraLoading);
    setLoadingState('attendance', attendanceLoading);
    setLoadingState('events', recordsLoading);
  }, [cameraLoading, attendanceLoading, recordsLoading, setLoadingState]);

  const timeStr = time.toTimeString().slice(0, 8);
  const dateStr = time.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

  const present = attendanceSummary?.present ?? 0;
  const absent = attendanceSummary?.absent ?? 0;
  const late = attendanceSummary?.late ?? 0;
  const total = attendanceSummary?.total ?? 0;

  // Transform camera health data for CameraCard component
  const cameras = useMemo(() => {
    if (!cameraHealth) return [];
    return Object.entries(cameraHealth).map(([id, cam]) => ({
      id,
      name: id === 'CAM1' ? 'Main Entrance' : id === 'CAM2' ? 'Corridor East' : id,
      location: id === 'CAM1' ? 'Block A – Ground' : id === 'CAM2' ? 'Block A – Level 1' : 'Unknown',
      status: cam.state as 'live' | 'recording' | 'alert' | 'offline',
      persons: 0, // Would come from attendance events
      fps: cam.current_fps ?? 0,
      resolution: cam.current_resolution ? `${cam.current_resolution[0]}x${cam.current_resolution[1]}` : '—',
      lastEvent: cam.last_frame_time ? `${Math.round((Date.now()/1000) - cam.last_frame_time)}s ago` : '—',
    }));
  }, [cameraHealth]);

  // Transform live events for EventRow component
  const events = useMemo(() => {
    if (!attendanceRecords?.records) return [];
    return attendanceRecords.records.slice(0, 20).map((evt: AttendanceRecord) => ({
      id: evt.attendanceRecordId,
      personId: evt.personId,
      personName: evt.personName,
      cameraId: evt.cameraId,
      trackId: evt.localTrackId,
      type: (evt.direction === 'in' ? 'enter' : evt.direction === 'out' ? 'exit' : 'unknown') as 'enter' | 'exit' | 'unknown',
      confidence: evt.identityConfidence,
      timestamp: new Date(evt.timestamp * 1000).toTimeString().slice(0, 8),
      observationId: evt.globalObservationId,
    }));
  }, [attendanceRecords]);

  return (
    <div className="flex h-full gap-3 p-3 fade-in">
      {/* Left: Camera Grid */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Stats bar */}
        <div className="flex items-center gap-3">
          <div className="glass-elevated flex items-center gap-4 px-4 py-2.5 rounded-xl flex-1">
            <div className="flex items-center gap-2">
              <StatusDot status={connected ? "live" : "offline"} />
              <span className="font-mono text-[11px] text-white/50 uppercase tracking-wider">System Live</span>
            </div>
            <div className="w-px h-4 bg-white/8" />
            <span className="font-mono text-xl font-semibold text-white tracking-widest">{timeStr}</span>
            <span className="font-mono text-[11px] text-white/40">{dateStr}</span>
            <div className="w-px h-4 bg-white/8" />
            <span className="font-mono text-[11px] text-white/40">{healthyCameras}/{totalCameras} cameras</span>
          </div>

          {/* Metric pills */}
          {[
            { label: "PRESENT", value: present, color: "text-emerald-400", bg: "bg-emerald-500/8 border-emerald-500/15" },
            { label: "LATE", value: late, color: "text-amber-400", bg: "bg-amber-500/8 border-amber-500/15" },
            { label: "ABSENT", value: absent, color: "text-rose-400", bg: "bg-rose-500/8 border-rose-500/15" },
            { label: "TOTAL", value: total, color: "text-white/70", bg: "bg-white/4 border-white/8" },
          ].map(m => (
            <div key={m.label} className={`glass-elevated flex flex-col items-center px-4 py-2 rounded-xl border ${m.bg}`}>
              <span className={`font-mono text-xl font-bold ${m.color}`}>{m.value}</span>
              <span className="font-mono text-[9px] text-white/30 uppercase tracking-[0.15em] mt-0.5">{m.label}</span>
            </div>
          ))}
        </div>

        {/* Camera grid */}
        <div className="flex-1 min-h-0">
          <SectionTitle>Camera Intelligence</SectionTitle>
          <div className="grid grid-cols-3 gap-2.5 h-[calc(100%-28px)]">
            {cameras.map(cam => (
              <CameraCard
                key={cam.id}
                cam={cam}
                onClick={() => setSelectedCam(selectedCam === cam.id ? null : cam.id)}
              />
            ))}
            {cameras.length === 0 && (
              <div className="col-span-3 flex items-center justify-center h-full text-white/30">
                No camera data available
              </div>
            )}
          </div>
        </div>

        {/* Bottom: attendance progress */}
        <div className="glass rounded-xl px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-white/40 uppercase tracking-[0.12em]">Attendance Coverage</span>
            <MonoValue>{total > 0 ? Math.round((present / total) * 100) : 0}% present</MonoValue>
          </div>
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden flex gap-0.5">
            <div className="h-full bg-emerald-400 rounded-full bar-fill transition-all" style={{ width: `${total > 0 ? (present / total) * 100 : 0}%` }} />
            <div className="h-full bg-amber-400 rounded-full bar-fill transition-all" style={{ width: `${total > 0 ? (late / total) * 100 : 0}%` }} />
            <div className="h-full bg-rose-400 rounded-full bar-fill transition-all" style={{ width: `${total > 0 ? (absent / total) * 100 : 0}%` }} />
          </div>
        </div>
      </div>

      {/* Right: Event stream */}
      <div className="w-72 flex flex-col gap-3">
        <div className="glass-elevated rounded-xl flex-1 flex flex-col min-h-0">
          <div className="px-3 pt-3 pb-2 flex items-center justify-between border-b border-white/6">
            <div className="flex items-center gap-2">
              <StatusDot status="live" />
              <span className="text-[11px] font-semibold text-white/50 uppercase tracking-[0.12em]">Live Events</span>
            </div>
            <MonoLabel>#{events[0]?.id?.split("-")[1] ?? "—"}</MonoLabel>
          </div>
          <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
            {events.length > 0 ? (
              events.map(evt => (
                <EventRow key={evt.id} event={evt} onClick={() => onPersonClick(evt.personId)} />
              ))
            ) : (
              <div className="text-center text-white/30 py-8 text-sm">No live events</div>
            )}
          </div>
        </div>

        {/* Alert panel */}
        <div className="glass-cyan rounded-xl p-3">
          <div className="flex items-center gap-2 mb-2">
            <StatusDot status="alert" />
            <span className="text-[11px] font-semibold text-amber-400/80 uppercase tracking-[0.12em]">System Status</span>
          </div>
          <div className="text-sm text-white/70 leading-relaxed">
            Overall: <span className={`font-mono text-[11px] ${isHealthy ? 'text-emerald-400' : isDegraded ? 'text-amber-400' : 'text-rose-400'}`}>{overallStatus}</span>
            {gpuHealthy ? ' · GPU: Healthy' : ' · GPU: Degraded'}
          </div>
          <div className="flex gap-2 mt-2.5">
            <GlassButton variant="cyan" className="text-xs flex-1" onClick={requestSync as () => void}>Sync</GlassButton>
            <GlassButton variant="ghost" className="text-xs" onClick={disconnect as () => void}>Disconnect</GlassButton>
          </div>
        </div>

        {/* Quick stats */}
        <div className="glass rounded-xl p-3 space-y-2">
          <SectionTitle>System Health</SectionTitle>
          {[
            { label: "Inference latency", value: "38 ms", ok: true },
            { label: "ArcFace DB size", value: "1,247 vectors", ok: true },
            { label: "Pending verif.", value: "3 events", ok: false },
            { label: "Disk (7d rolling)", value: "142 GB / 500 GB", ok: true },
          ].map(s => (
            <div key={s.label} className="flex items-center justify-between">
              <MonoLabel>{s.label}</MonoLabel>
              <MonoValue className={s.ok ? "text-white/70" : "text-amber-400"}>{s.value}</MonoValue>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}