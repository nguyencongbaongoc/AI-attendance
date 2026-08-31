import { useEffect } from 'react';
import { useUIStore, useHealthStore, useAttendanceStore, initializeMockData } from '@/store';
import { useHealthRealtime } from '@/hooks/useHealth';
import { healthWS } from '@/services/api';
import CommandCenter from '@/pages/CommandCenter';
import PersonSearch from '@/pages/PersonSearch';
import PersonDetail from '@/pages/PersonDetail';
import AnnotatedReplay from '@/pages/AnnotatedReplay';
import ProvenanceChain from '@/pages/ProvenanceChain';
import EnrollmentDB from '@/pages/EnrollmentDB';
import TimetableManagement from '@/pages/TimetableManagement';
import ParentTelegram from '@/pages/ParentTelegram';
import ExcelExport from '@/pages/ExcelExport';
import SystemHealth from '@/pages/SystemHealth';
import { ThemeProvider, useTheme } from '@/context/ThemeContext';
import { NotificationProvider, useNotifications } from '@/context/NotificationContext';
import './index.css';

// Design System Components (preserved from original Figma App.tsx)
function Badge({ type }: { type: string }) {
  const map: Record<string, string> = {
    present: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    absent: "bg-rose-500/15 text-rose-400 border-rose-500/25",
    late: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    excused: "bg-violet-500/15 text-violet-400 border-violet-500/25",
    live: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
    recording: "bg-rose-500/15 text-rose-400 border-rose-500/25",
    alert: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    offline: "bg-white/5 text-white/30 border-white/10",
    enter: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    exit: "bg-rose-500/15 text-rose-400 border-rose-500/25",
    unknown: "bg-white/5 text-white/40 border-white/10",
    student: "bg-cyan-500/10 text-cyan-300 border-cyan-500/20",
    staff: "bg-violet-500/10 text-violet-300 border-violet-500/20",
    visitor: "bg-amber-500/10 text-amber-300 border-amber-500/20",
    verified: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    pending: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    flagged: "bg-rose-500/15 text-rose-400 border-rose-500/25",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border uppercase tracking-wider ${map[type] ?? "bg-white/5 text-white/40 border-white/10"}`}>
      {type}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    live: "bg-cyan-400",
    recording: "bg-rose-400",
    alert: "bg-amber-400",
    offline: "bg-white/20",
    present: "bg-emerald-400",
    absent: "bg-rose-400",
    late: "bg-amber-400",
    excused: "bg-violet-400",
  };
  const glow: Record<string, string> = {
    live: "shadow-[0_0_6px_rgba(0,212,255,0.8)]",
    recording: "shadow-[0_0_6px_rgba(244,63,94,0.8)]",
    alert: "shadow-[0_0_6px_rgba(245,158,11,0.8)]",
    present: "shadow-[0_0_6px_rgba(16,185,129,0.8)]",
  };
  return (
    <span className="relative inline-flex items-center justify-center w-2.5 h-2.5">
      {(status === "live" || status === "alert" || status === "present") && (
        <span className={`absolute w-2.5 h-2.5 rounded-full ${colors[status]} opacity-40 pulse-ring`} />
      )}
      <span className={`relative w-2 h-2 rounded-full ${colors[status] ?? "bg-white/20"} ${glow[status] ?? ""} pulse-dot`} />
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.9 ? "bg-cyan-400" : value >= 0.7 ? "bg-amber-400" : "bg-rose-400";
  const textColor = value >= 0.9 ? "text-cyan-400" : value >= 0.7 ? "text-amber-400" : "text-rose-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full rounded-full bar-fill ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`font-mono text-[11px] font-medium w-10 text-right ${textColor}`}>{pct}%</span>
    </div>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

function MonoLabel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono text-[11px] text-white/40 tracking-wide ${className}`}>{children}</span>;
}

function MonoValue({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] text-white/80 ${className}`}>{children}</span>;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <div className="w-0.5 h-4 bg-cyan-400 rounded-full" />
      <span className="text-[11px] font-semibold text-white/40 uppercase tracking-[0.15em]">{children}</span>
    </div>
  );
}

function GlassButton({ children, onClick, variant = "default", className = "", disabled = false }: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "default" | "cyan" | "violet" | "danger" | "ghost";
  className?: string;
  disabled?: boolean;
}) {
  const variants = {
    default: "bg-white/5 border-white/10 text-white/70 hover:bg-white/10 hover:border-white/20 hover:text-white",
    cyan: "bg-cyan-500/10 border-cyan-500/25 text-cyan-400 hover:bg-cyan-500/20 hover:border-cyan-500/40 hover:shadow-[0_0_16px_rgba(0,212,255,0.2)]",
    violet: "bg-violet-500/10 border-violet-500/25 text-violet-400 hover:bg-violet-500/20 hover:border-violet-500/40 hover:shadow-[0_0_16px_rgba(139,92,246,0.2)]",
    danger: "bg-rose-500/10 border-rose-500/25 text-rose-400 hover:bg-rose-500/20 hover:border-rose-500/40",
    ghost: "bg-transparent border-transparent text-white/50 hover:text-white/80 hover:bg-white/5",
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-lg border text-sm font-medium transition-all duration-200 min-w-[44px] min-h-[44px] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

function GlassInput({ placeholder, value, onChange, prefix, className = "" }: {
  placeholder?: string;
  value?: string;
  onChange?: (v: string) => void;
  prefix?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`relative flex items-center ${className}`}>
      {prefix && <span className="absolute left-3 text-white/30">{prefix}</span>}
      <input
        type="text"
        value={value}
        onChange={e => onChange?.(e.target.value)}
        placeholder={placeholder}
        className={`w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] ${prefix ? "pl-9 pr-4" : "px-4"}`}
      />
    </div>
  );
}

// Navigation Items
const NAV_ITEMS: { id: string; label: string; icon: React.ReactNode; shortkey: string }[] = [
  {
    id: "command", label: "Command", shortkey: "F1",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>,
  },
  {
    id: "search", label: "Persons", shortkey: "F2",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
  },
  {
    id: "replay", label: "Replay", shortkey: "F3",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>,
  },
  {
    id: "provenance", label: "Provenance", shortkey: "F4",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  },
  {
    id: "enrollment", label: "Enrollment", shortkey: "F5",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>,
  },
  {
    id: "timetable", label: "Timetable", shortkey: "F6",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
  },
  {
    id: "parents", label: "Parents", shortkey: "F7",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  },
  {
    id: "excel", label: "Excel", shortkey: "F8",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>,
  },
  {
    id: "system", label: "System", shortkey: "F9",
    icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  },
];

function AppContent() {
  const { 
    activeScreen, 
    setActiveScreen, 
    detailPersonId, 
    setDetailPersonId,
    sidebarCollapsed,
    toggleSidebar,
    loadingStates,
    setLoadingState,
  } = useUIStore();
  
  const { setSystemHealth, setCameraHealth, setGPUStatus, setMetrics, setHealthSnapshot, setRealtimeConnected, setRealtimeError } = useHealthStore();
  const { setAttendanceSummary, addLiveEvent, setLiveEvents, selectPerson, clearSelectedPerson } = useAttendanceStore();
  
  const { snapshot, connected, error, requestSync, disconnect } = useHealthRealtime(true);

  // Initialize mock data for development only
  useEffect(() => {
    if (import.meta.env.DEV) {
      initializeMockData();
    }
  }, []);

  // Connect to realtime health updates
  useEffect(() => {
    if (connected && snapshot) {
      setRealtimeConnected(true);
      setRealtimeError(null);
      
      // Update health stores from realtime snapshot
      if (snapshot.type === 'health_update' || snapshot.type === 'sync_response') {
        setSystemHealth({
          timestamp: snapshot.timestamp,
          overall_status: snapshot.overall_status,
          components: snapshot.components,
          cameras: snapshot.cameras,
          gpu: snapshot.gpu,
          runtime: snapshot.runtime,
        });
        setCameraHealth(snapshot.cameras);
        setGPUStatus(snapshot.gpu);
        setMetrics({
          timestamp: snapshot.timestamp,
          camera_metrics: {},
          queue_metrics: snapshot.queue_metrics,
          attendance_metrics: { total_students: 0, present_today: 0, absent_today: 0, late_today: 0, left_early_today: 0 },
          policy_metrics: { morning_absence_events: 0, long_exit_events: 0, missing_checkout_events: 0, short_exit_events: 0, deduplicated_events: 0 },
          telegram_metrics: { worker_running: false, messages_sent: 0, messages_failed: 0, last_send_time: null },
          database_metrics: snapshot.database_metrics,
        });
        setHealthSnapshot(snapshot);
      }
    } else if (error) {
      setRealtimeError(error);
      setRealtimeConnected(false);
    }
  }, [connected, snapshot, error, setRealtimeConnected, setRealtimeError, setSystemHealth, setCameraHealth, setGPUStatus, setMetrics, setHealthSnapshot]);

  // Handle person click from any screen
  const handlePersonClick = (personId: string) => {
    setDetailPersonId(personId);
    setActiveScreen('person');
  };

  // Handle back from person detail
  const handleBackFromDetail = () => {
    setDetailPersonId(null);
    setActiveScreen('search');
  };

  // Handle attendance event from realtime
  useEffect(() => {
    if (snapshot?.type === 'health_update' && snapshot.cameras) {
      // Could add logic here to detect new attendance events from camera health changes
    }
  }, [snapshot]);

  const renderScreen = () => {
    switch (activeScreen) {
      case 'command':
        return <CommandCenter onPersonClick={handlePersonClick} />;
      case 'search':
        return <PersonSearch onPersonClick={handlePersonClick} />;
      case 'person':
        return detailPersonId ? (
          <PersonDetail personId={detailPersonId} onBack={handleBackFromDetail} />
        ) : (
          <PersonSearch onPersonClick={handlePersonClick} />
        );
      case 'replay':
        return <AnnotatedReplay />;
      case 'provenance':
        return <ProvenanceChain />;
      case 'enrollment':
        return <EnrollmentDB onPersonClick={handlePersonClick} />;
      case 'timetable':
        return <TimetableManagement />;
      case 'parents':
        return <ParentTelegram />;
      case 'excel':
        return <ExcelExport />;
      case 'system':
        return <SystemHealth />;
      default:
        return <CommandCenter onPersonClick={handlePersonClick} />;
    }
  };

  return (
    <div className="bg-mesh flex flex-col h-screen overflow-hidden select-none">
      {/* Top navigation bar */}
      <nav className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-white/6" style={{
        background: "rgba(4, 6, 15, 0.9)",
        backdropFilter: "blur(20px)",
      }}>
        {/* Wordmark */}
        <div className="flex items-center gap-2.5 mr-4">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-500/30 to-violet-500/30 border border-cyan-400/30 flex items-center justify-center">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" strokeWidth="1.5">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </div>
          <div>
            <div className="text-[12px] font-bold text-white/90 tracking-tight leading-none">ATTENDAI</div>
            <div className="font-mono text-[8px] text-white/30 tracking-widest uppercase leading-none mt-0.5">Command Center</div>
          </div>
        </div>

        {/* Nav items */}
        <div className="flex items-center gap-1">
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              onClick={() => { 
                setActiveScreen(item.id); 
                if (item.id !== "person") setDetailPersonId(null); 
              }}
              className={`flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-medium border transition-all duration-200 cursor-pointer min-w-[44px] ${(activeScreen === item.id || (item.id === "search" && activeScreen === "person")) ? "nav-active" : "nav-inactive"}`}
            >
              {item.icon}
              {item.label}
              <span className="font-mono text-[9px] opacity-40 ml-0.5">{item.shortkey}</span>
            </button>
          ))}
        </div>

        {/* Right status bar */}
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <StatusDot status={connected ? "live" : "offline"} />
            <span className="font-mono text-[10px] text-white/35 uppercase tracking-wider">
              {connected ? "Real-time Connected" : "Real-time Disconnected"}
            </span>
          </div>
          <div className="w-px h-4 bg-white/8" />
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-5 rounded-full bg-gradient-to-br from-cyan-500/30 to-violet-500/30 border border-white/10 flex items-center justify-center">
              <span className="font-mono text-[7px] text-white/60">AD</span>
            </div>
            <span className="font-mono text-[10px] text-white/35">admin</span>
          </div>
        </div>
      </nav>

      {/* Screen content */}
      <main className="flex-1 min-h-0 overflow-hidden">
        {renderScreen()}
      </main>

      {/* Bottom status strip */}
      <div className="shrink-0 flex items-center gap-4 px-4 py-1.5 border-t border-white/5" style={{
        background: "rgba(4, 6, 15, 0.7)",
        backdropFilter: "blur(12px)",
      }}>
        <MonoLabel>SYS · v2.4.1</MonoLabel>
        <span className="text-white/10">·</span>
        <MonoLabel>ArcFace R100 v2.1</MonoLabel>
        <span className="text-white/10">·</span>
        <MonoLabel>GPU: RTX 4090 · 38ms latency</MonoLabel>
        <span className="text-white/10">·</span>
        <MonoLabel>6 cameras · 5 active</MonoLabel>
      <div className="ml-auto flex items-center gap-4">
          <MonoLabel>WS: {connected ? "Connected" : "Disconnected"}</MonoLabel>
          <span className="text-white/10">·</span>
          <MonoLabel>KHKT 2026 · Smart Campus AI</MonoLabel>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <NotificationProvider>
        <AppContent />
      </NotificationProvider>
    </ThemeProvider>
  );
}
