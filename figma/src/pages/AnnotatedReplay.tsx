// Annotated Replay Page - Migrated from original Figma App.tsx AnnotatedReplay component
// Now uses real backend data via hooks and store

import { useState, useEffect, useMemo } from 'react';
import { useAttendanceStore } from '@/store';
import type { AttendanceRecord } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, ConfidenceBar, StatusDot } from '@/components/ui/DesignSystem';

export default function AnnotatedReplay() {
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0.34);
  const [selectedTrack, setSelectedTrack] = useState("TRK-441");
  const { liveEvents } = useAttendanceStore();

  const tracks = useMemo(() => [
    { id: "TRK-441", person: "Aisha Rahman", conf: 0.984, color: "cyan" },
    { id: "TRK-440", person: "Reza Putra", conf: 0.961, color: "violet" },
    { id: "TRK-439", person: "Mei Ling", conf: 0.877, color: "amber" },
  ], []);

  const annotations = useMemo(() => [
    { time: 0.15, type: "enter", label: "TRK-441 ENTER" },
    { time: 0.3, type: "enter", label: "TRK-440 ENTER" },
    { time: 0.34, type: "unknown", label: "UNK detected" },
    { time: 0.55, type: "exit", label: "TRK-441 EXIT" },
    { time: 0.7, type: "enter", label: "TRK-439 ENTER" },
  ], []);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      setProgress(p => {
        if (p >= 1) { setPlaying(false); return 1; }
        return p + 0.002;
      });
    }, 50);
    return () => clearInterval(t);
  }, [playing]);

  const formatTime = (pct: number) => {
    const total = 300;
    const secs = Math.round(pct * total);
    const m = Math.floor(secs / 60).toString().padStart(2, "0");
    const s = (secs % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  const trackColors: Record<string, string> = { cyan: "#00d4ff", violet: "#8b5cf6", amber: "#f59e0b" };

  return (
    <div className="flex h-full gap-3 p-3 fade-in">
      {/* Main viewport */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Camera selector */}
        <div className="flex items-center gap-2">
          {["CAM-001", "CAM-002", "CAM-003", "CAM-004", "CAM-005", "CAM-006"].map(cam => (
            <button
              key={cam}
              className={`h-9 px-3 rounded-lg text-[11px] font-mono border transition-all duration-150 cursor-pointer min-w-[44px] ${cam === "CAM-001" ? "nav-active" : "nav-inactive"}`}
            >
              {cam}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1.5">
            <MonoLabel>Main Entrance · 2026-08-23</MonoLabel>
          </div>
        </div>

        {/* Video viewport */}
        <div className="relative flex-1 rounded-xl overflow-hidden scanline" style={{
          background: "linear-gradient(135deg, #001420, #002840, #001428)",
          minHeight: 0,
        }}>
          {/* Noise */}
          <div className="absolute inset-0 opacity-15" style={{
            backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.4'/%3E%3C/svg%3E\")",
          }} />

          {/* Detection boxes */}
          {tracks.map((track, i) => (
            <div
              key={track.id}
              onClick={() => setSelectedTrack(track.id)}
              className="absolute cursor-pointer transition-all duration-300"
              style={{
                left: `${20 + i * 22}%`,
                top: "25%",
                width: "12%",
                height: "45%",
                border: `1px solid ${trackColors[track.color]}${selectedTrack === track.id ? "cc" : "66"}`,
                boxShadow: selectedTrack === track.id ? `0 0 12px ${trackColors[track.color]}44` : "none",
                borderRadius: 4,
              }}
            >
              {/* Label */}
              <div className="absolute -top-5 left-0 flex items-center gap-1 whitespace-nowrap">
                <div className="h-px w-3" style={{ background: trackColors[track.color] }} />
                <span className="font-mono text-[9px]" style={{ color: trackColors[track.color] }}>{track.id}</span>
              </div>
              {/* Confidence */}
              <div className="absolute -bottom-5 left-0">
                <span className="font-mono text-[9px]" style={{ color: trackColors[track.color] }}>{(track.conf * 100).toFixed(0)}%</span>
              </div>
              {/* Silhouette */}
              <div className="absolute inset-2 flex flex-col items-center justify-end gap-1">
                <div className="w-5 h-5 rounded-full opacity-30" style={{ background: trackColors[track.color] }} />
                <div className="w-7 h-10 rounded-t-full opacity-20" style={{ background: trackColors[track.color] }} />
              </div>
            </div>
          ))}

          {/* Corner UI */}
          <div className="absolute top-3 left-3 flex items-center gap-2">
            <StatusDot status="recording" />
            <span className="font-mono text-[10px] text-white/50">REC · CAM-001</span>
          </div>
          <div className="absolute top-3 right-3">
            <span className="font-mono text-[10px] text-white/50">2026-08-23 · {formatTime(progress)}</span>
          </div>

          {/* Corner brackets */}
          {[["top-3 left-3", "border-t border-l"], ["top-3 right-3", "border-t border-r"], ["bottom-14 left-3", "border-b border-l"], ["bottom-14 right-3", "border-b border-r"]].map(([pos, border]) => (
            <div key={pos} className={`absolute ${pos} w-5 h-5 ${border} border-cyan-400/20`} />
          ))}

          {/* Playback controls */}
          <div className="absolute bottom-0 left-0 right-0 px-4 py-3 bg-gradient-to-t from-black/80 to-transparent">
            {/* Progress bar with annotations */}
            <div className="relative mb-3">
              <div
                className="relative h-1 bg-white/10 rounded-full cursor-pointer overflow-hidden"
                onClick={e => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setProgress((e.clientX - rect.left) / rect.width);
                }}
              >
                <div className="h-full bg-cyan-400 rounded-full" style={{ width: `${progress * 100}%` }} />
              </div>
              {/* Annotation markers */}
              {annotations.map(a => (
                <div
                  key={a.label}
                  className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full -translate-x-1/2"
                  style={{
                    left: `${a.time * 100}%`,
                    background: a.type === "enter" ? "#10b981" : a.type === "exit" ? "#f43f5e" : "#f59e0b",
                  }}
                  title={a.label}
                />
              ))}
            </div>

            <div className="flex items-center gap-3">
              <GlassButton variant="ghost" className="h-8 min-h-0 px-2" onClick={() => setProgress(Math.max(0, progress - 0.05))}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/>
                </svg>
              </GlassButton>
              <GlassButton variant="cyan" className="h-8 min-h-0 px-3" onClick={() => setPlaying(p => !p)}>
                {playing ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>
                  </svg>
                ) : (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                  </svg>
                )}
              </GlassButton>
              <GlassButton variant="ghost" className="h-8 min-h-0 px-2" onClick={() => setProgress(Math.min(1, progress + 0.05))}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>
                </svg>
              </GlassButton>
              <span className="font-mono text-[11px] text-white/50">{formatTime(progress)} / 05:00</span>
              <div className="ml-auto flex items-center gap-2">
                <MonoLabel>Speed:</MonoLabel>
                {["0.5×", "1×", "2×", "4×"].map(s => (
                  <button key={s} className={`font-mono text-[10px] px-1.5 py-0.5 rounded border transition-all cursor-pointer ${s === "1×" ? "border-cyan-400/30 text-cyan-400 bg-cyan-400/10" : "border-white/10 text-white/35 hover:text-white/60"}`}>{s}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right sidebar: track details */}
      <div className="w-64 flex flex-col gap-3">
        <div className="glass-elevated rounded-xl p-3 flex-1 flex flex-col min-h-0">
          <SectionTitle>Track Details</SectionTitle>
          <div className="space-y-2 flex-1 overflow-y-auto">
            {tracks.map(track => (
              <div
                key={track.id}
                onClick={() => setSelectedTrack(track.id)}
                className={`p-3 rounded-lg cursor-pointer transition-all duration-150 border ${selectedTrack === track.id ? "border-cyan-400/20 bg-cyan-400/8" : "border-transparent hover:border-white/6 hover:bg-white/3"}`}
              >
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full" style={{ background: trackColors[track.color] }} />
                  <span className="font-mono text-[11px] text-white/80 font-medium">{track.id}</span>
                </div>
                <div className="text-[12px] text-white/65 mt-1">{track.person}</div>
                <div className="mt-2">
                  <ConfidenceBar value={track.conf} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="glass rounded-xl p-3">
          <SectionTitle>Event Log</SectionTitle>
          <div className="space-y-1">
            {annotations.map(a => (
              <div
                key={a.label}
                className="flex items-center gap-2 py-1.5 cursor-pointer hover:bg-white/3 rounded px-1"
                onClick={() => setProgress(a.time)}
              >
                <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{
                  background: a.type === "enter" ? "#10b981" : a.type === "exit" ? "#f43f5e" : "#f59e0b",
                }} />
                <MonoLabel className="flex-1">{a.label}</MonoLabel>
                <MonoLabel>{formatTime(a.time)}</MonoLabel>
              </div>
            ))}
          </div>
        </div>

        <div className="glass rounded-xl p-3 space-y-2">
          <SectionTitle>Metadata</SectionTitle>
          {[
            { label: "Camera", value: "CAM-001" },
            { label: "Clip ID", value: "CLIP-20260823-001" },
            { label: "Duration", value: "05:00" },
            { label: "Resolution", value: "3840×2160" },
            { label: "Model", value: "ArcFace R100" },
          ].map(r => (
            <div key={r.label} className="flex items-center justify-between">
              <MonoLabel>{r.label}</MonoLabel>
              <MonoValue className="text-[10px]">{r.value}</MonoValue>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}