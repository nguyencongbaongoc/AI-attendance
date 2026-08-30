// Design System Components - Preserved from original Figma App.tsx
// These are the core UI building blocks for the liquid-glass design language

import React from 'react';

export function Badge({ type }: { type: string }) {
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
    <span 
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border uppercase tracking-wider ${map[type] ?? "bg-white/5 text-white/40 border-white/10"}`}
      role="status"
      aria-label={`Status: ${type}`}
    >
      {type}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    live: "bg-cyan-400",
    recording: "bg-rose-400",
    alert: "bg-amber-400",
    offline: "bg-white/20",
    present: "bg-emerald-400",
    absent: "bg-rose-400",
    late: "bg-amber-400",
    excused: "bg-violet-400",
    degraded: "bg-amber-400",
    stale: "bg-amber-400",
  };
  const glow: Record<string, string> = {
    live: "shadow-[0_0_6px_rgba(0,212,255,0.8)]",
    recording: "shadow-[0_0_6px_rgba(244,63,94,0.8)]",
    alert: "shadow-[0_0_6px_rgba(245,158,11,0.8)]",
    present: "shadow-[0_0_6px_rgba(16,185,129,0.8)]",
    degraded: "shadow-[0_0_6px_rgba(245,158,11,0.8)]",
    stale: "shadow-[0_0_6px_rgba(245,158,11,0.8)]",
  };
  const statusLabels: Record<string, string> = {
    live: "Live",
    recording: "Recording",
    alert: "Alert",
    offline: "Offline",
    present: "Present",
    absent: "Absent",
    late: "Late",
    excused: "Excused",
    degraded: "Degraded",
    stale: "Stale",
  };
  return (
    <span 
      className="relative inline-flex items-center justify-center w-2.5 h-2.5"
      role="status"
      aria-label={`Status: ${statusLabels[status] ?? status}`}
    >
      {(status === "live" || status === "alert" || status === "present" || status === "degraded" || status === "stale") && (
        <span className={`absolute w-2.5 h-2.5 rounded-full ${colors[status]} opacity-40 pulse-ring`} aria-hidden="true" />
      )}
      <span className={`relative w-2 h-2 rounded-full ${colors[status] ?? "bg-white/20"} ${glow[status] ?? ""} pulse-dot`} aria-hidden="true" />
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
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

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function MonoLabel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono text-[11px] text-white/40 tracking-wide ${className}`}>{children}</span>;
}

export function MonoValue({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] text-white/80 ${className}`}>{children}</span>;
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <div className="w-0.5 h-4 bg-cyan-400 rounded-full" />
      <span className="text-[11px] font-semibold text-white/40 uppercase tracking-[0.15em]">{children}</span>
    </div>
  );
}

export function GlassButton({ children, onClick, variant = "default", className = "", disabled = false, type = "button" }: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "default" | "cyan" | "violet" | "danger" | "ghost";
  className?: string;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
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
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-lg border text-sm font-medium transition-all duration-200 min-w-[44px] min-h-[44px] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function GlassInput({ placeholder, value, onChange, prefix, className = "" }: {
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
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

// Glass panel variants
export function GlassPanel({ children, className = "", elevated = false }: {
  children: React.ReactNode;
  className?: string;
  elevated?: boolean;
}) {
  return (
    <div className={`rounded-xl border ${elevated ? "bg-white/5 shadow-[0_0_24px_rgba(0,0,0,0.3)]" : "bg-white/3"} border-white/10 ${className}`}>
      {children}
    </div>
  );
}

export function GlassElevated({ children, className = "" }: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl bg-white/5 border border-white/10 shadow-[0_0_24px_rgba(0,0,0,0.3)] ${className}`}>
      {children}
    </div>
  );
}

export function GlassCyan({ children, className = "" }: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl bg-cyan-500/5 border border-cyan-500/15 ${className}`}>
      {children}
    </div>
  );
}

// Animation keyframes (injected via CSS)
export const keyframes = `
@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 0.4; }
  50% { transform: scale(1.5); opacity: 0; }
  100% { transform: scale(1); opacity: 0.4; }
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes bar-fill {
  from { width: 0%; }
  to { width: var(--target-width); }
}

.fade-in {
  animation: fade-in 0.3s ease-out forwards;
}

.skeleton {
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.bar-fill {
  animation: bar-fill 0.5s ease-out forwards;
}

.scanline::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.03) 2px,
    rgba(0,0,0,0.03) 4px
  );
  pointer-events: none;
  opacity: 0.5;
}

.pulse-ring {
  animation: pulse-ring 2s ease-in-out infinite;
}

.pulse-dot {
  animation: pulse-dot 2s ease-in-out infinite;
}

.nav-active {
  background: rgba(6, 182, 212, 0.15);
  border-color: rgba(6, 182, 212, 0.3);
  color: #00d4ff;
}

.nav-inactive {
  color: rgba(255,255,255,0.5);
  border-color: transparent;
}

.nav-inactive:hover {
  background: rgba(255,255,255,0.05);
  border-color: rgba(255,255,255,0.1);
  color: white;
}
`;