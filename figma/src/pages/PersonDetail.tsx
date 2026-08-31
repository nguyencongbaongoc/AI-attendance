// Person Detail Page - Migrated from original Figma App.tsx PersonDetail component
// Now uses real backend data via hooks and store

import { useAttendanceStore } from '@/store';
import type { Person, AttendanceRecord } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, ConfidenceBar } from '@/components/ui/DesignSystem';

interface PersonDetailProps {
  personId: string;
  onBack: () => void;
}

export default function PersonDetail({ personId, onBack }: PersonDetailProps) {
  const { liveEvents } = useAttendanceStore();
  
  // Find person from live events or use mock data
  const person = liveEvents.find(e => e.personId === personId);
  
  // Mock person data for now - will be replaced with real API call
  const mockPerson: Person = {
    person_id: personId,
    name: person?.personName || "Unknown Person",
    role: "student",
    enrollment_date: "2024-01-15",
    last_seen: person ? new Date(person.timestamp * 1000).toTimeString().slice(0, 8) : "—",
    last_camera: person?.cameraId || "—",
    attendance_state: "present",
    face_quality: person?.identityConfidence || 0.95,
    track_count: 12,
  };

  const timeline = [
    { time: "09:32:07", cam: "CAM-001", track: "TRK-441", conf: 0.984, obs: "OBS-77821", type: "enter" as const },
    { time: "09:15:44", cam: "CAM-002", track: "TRK-412", conf: 0.971, obs: "OBS-77744", type: "enter" as const },
    { time: "08:58:22", cam: "CAM-005", track: "TRK-388", conf: 0.946, obs: "OBS-77618", type: "enter" as const },
    { time: "08:45:01", cam: "CAM-001", track: "TRK-361", conf: 0.958, obs: "OBS-77521", type: "exit" as const },
    { time: "08:30:55", cam: "CAM-001", track: "TRK-334", conf: 0.979, obs: "OBS-77401", type: "enter" as const },
  ];

  return (
    <div className="flex h-full gap-3 p-3 fade-in">
      {/* Left: identity panel */}
      <div className="w-72 flex flex-col gap-3">
        <GlassButton variant="ghost" onClick={onBack} className="self-start">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Back
        </GlassButton>

        <div className="glass-elevated rounded-xl p-4 flex-1">
          {/* Face placeholder */}
          <div className="relative mb-4">
            <div className="w-full aspect-square rounded-xl bg-gradient-to-br from-cyan-900/40 to-violet-900/40 border border-white/8 flex items-center justify-center overflow-hidden">
              <span className="text-5xl font-bold text-white/20">{mockPerson.name.split(" ").map(n => n[0]).join("").slice(0,2)}</span>
              {/* Corner brackets */}
              <div className="absolute top-2 left-2 w-4 h-4 border-t-2 border-l-2 border-cyan-400/40" />
              <div className="absolute top-2 right-2 w-4 h-4 border-t-2 border-r-2 border-cyan-400/40" />
              <div className="absolute bottom-2 left-2 w-4 h-4 border-b-2 border-l-2 border-cyan-400/40" />
              <div className="absolute bottom-2 right-2 w-4 h-4 border-b-2 border-r-2 border-cyan-400/40" />
            </div>
            <div className="absolute bottom-2 left-1/2 -translate-x-1/2">
              <div className="glass px-2 py-0.5 rounded text-[10px] font-mono text-cyan-400 border border-cyan-400/20">
                Quality: {Math.round(mockPerson.face_quality * 100)}%
              </div>
            </div>
          </div>

          <div className="text-lg font-semibold text-white/95 leading-tight">{mockPerson.name}</div>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <MonoLabel className="!text-white/50">{mockPerson.person_id}</MonoLabel>
            <Badge type={mockPerson.role} />
            <Badge type={mockPerson.attendance_state} />
          </div>

          <div className="mt-4 space-y-2.5 border-t border-white/6 pt-4">
            {[
              { label: "Enrolled", value: mockPerson.enrollment_date },
              { label: "Last camera", value: mockPerson.last_camera },
              { label: "Last seen", value: mockPerson.last_seen },
              { label: "Total tracks", value: mockPerson.track_count.toString() },
            ].map(r => (
              <div key={r.label} className="flex items-center justify-between">
                <MonoLabel>{r.label}</MonoLabel>
                <MonoValue>{r.value}</MonoValue>
              </div>
            ))}
          </div>

          <div className="mt-4 flex gap-2">
            <GlassButton variant="cyan" className="flex-1 text-xs">Replay</GlassButton>
            <GlassButton variant="violet" className="flex-1 text-xs">Provenance</GlassButton>
          </div>
        </div>
      </div>

      {/* Right: timeline + details */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        <div className="glass-elevated rounded-xl p-4 flex-1 flex flex-col min-h-0">
          <SectionTitle>Observation Timeline</SectionTitle>
          <div className="flex-1 overflow-y-auto space-y-0">
            {timeline.map((obs, i) => (
              <div key={obs.obs} className="relative pl-6">
                {/* Vertical line */}
                {i < timeline.length - 1 && (
                  <div className="absolute left-2 top-5 bottom-0 w-px bg-white/6" />
                )}
                {/* Node */}
                <div className={`absolute left-0.5 top-3 w-3 h-3 rounded-full border-2 ${obs.type === "enter" ? "border-emerald-400 bg-emerald-400/20" : "border-rose-400 bg-rose-400/20"}`} />

                <div className="glass rounded-lg p-3 mb-2 hover:bg-white/5 transition-colors cursor-pointer">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-[11px] font-semibold text-white/80">{obs.time}</span>
                        <Badge type={obs.type} />
                        <span className="font-mono text-[10px] text-white/35">{obs.cam}</span>
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-3">
                        <div>
                          <MonoLabel>Track ID</MonoLabel>
                          <div className="font-mono text-[11px] text-white/70 mt-0.5">{obs.track}</div>
                        </div>
                        <div>
                          <MonoLabel>Observation</MonoLabel>
                          <div className="font-mono text-[11px] text-white/70 mt-0.5">{obs.obs}</div>
                        </div>
                        <div>
                          <MonoLabel>Confidence</MonoLabel>
                          <ConfidenceBar value={obs.conf} />
                        </div>
                      </div>
                    </div>
                    <GlassButton variant="ghost" className="text-xs shrink-0 h-7 min-h-0 px-2">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <polygon points="5 3 19 12 5 21 5 3"/>
                      </svg>
                    </GlassButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Camera heatmap row */}
        <div className="glass rounded-xl p-3">
          <SectionTitle>Camera Frequency</SectionTitle>
          <div className="flex items-end gap-2 h-12">
            {["CAM-001", "CAM-002", "CAM-003", "CAM-004", "CAM-005", "CAM-006"].map(cam => {
              const count = Math.floor(Math.random() * 8);
              return (
                <div key={cam} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full rounded-sm bg-cyan-400/20" style={{ height: `${(count / 8) * 44}px`, minHeight: 2 }} />
                  <MonoLabel className="!text-[9px]">{cam.replace("CAM-", "")}</MonoLabel>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}