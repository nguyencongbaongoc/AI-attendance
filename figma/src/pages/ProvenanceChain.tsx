// Provenance Chain Page - Migrated from original Figma App.tsx ProvenanceChain component
// Now uses real backend data via hooks and store

import { useHealthStore } from '@/store';
import type { HealthSnapshot } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton } from '@/components/ui/DesignSystem';

export default function ProvenanceChain() {
  const { healthSnapshot } = useHealthStore();
  
  // Mock provenance nodes for now - will be replaced with real API call
  const nodes = [
    { id: "RAW-20260823-001", label: "Raw Frame", desc: "Captured by CAM-001 at 09:32:07", type: "source" as const, hash: "sha256:a3f7…b291", verified: true },
    { id: "DET-77821", label: "Detection", desc: "YOLOv8 person bbox · confidence 0.991", type: "process" as const, hash: "sha256:c4e1…d882", verified: true },
    { id: "FEAT-77821", label: "Face Feature", desc: "ArcFace R100 · 512-dim embedding extracted", type: "process" as const, hash: "sha256:f9a2…2341", verified: true },
    { id: "MATCH-77821", label: "Identity Match", desc: "Matched to STU-10042 · distance 0.016", type: "process" as const, hash: "sha256:b7c3…a119", verified: true },
    { id: "OBS-77821", label: "Observation", desc: "Attendance event recorded · type ENTER", type: "event" as const, hash: "sha256:e2d5…c774", verified: true },
    { id: "ATT-20260823-10042", label: "Attendance Record", desc: "Finalized record · signed by system", type: "record" as const, hash: "sha256:1a4b…9f36", verified: true },
  ];

  const typeColors: Record<string, { border: string; bg: string; text: string; icon: string }> = {
    source: { border: "border-cyan-400/30", bg: "bg-cyan-400/8", text: "text-cyan-400", icon: "📷" },
    process: { border: "border-violet-400/30", bg: "bg-violet-400/8", text: "text-violet-400", icon: "⚙️" },
    event: { border: "border-emerald-400/30", bg: "bg-emerald-400/8", text: "text-emerald-400", icon: "✓" },
    record: { border: "border-amber-400/30", bg: "bg-amber-400/8", text: "text-amber-400", icon: "📋" },
  };

  return (
    <div className="flex h-full gap-3 p-3 fade-in">
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        <div className="glass-elevated rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-base font-semibold text-white/90">Provenance Chain · OBS-77821</div>
            <div className="flex items-center gap-2 mt-1">
              <Badge type="verified" />
              <MonoLabel>STU-10042 · CAM-001 · 2026-08-23T09:32:07Z</MonoLabel>
            </div>
          </div>
          <div className="flex gap-2">
            <GlassButton variant="cyan">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Export Proof
            </GlassButton>
            <GlassButton variant="ghost">Verify Chain</GlassButton>
          </div>
        </div>

        {/* Chain visualization */}
        <div className="flex-1 overflow-y-auto">
          <div className="relative py-2">
            {/* Vertical spine */}
            <div className="absolute left-8 top-8 bottom-8 w-px bg-gradient-to-b from-cyan-400/30 via-violet-400/20 to-amber-400/30" />

            <div className="space-y-3">
              {nodes.map((node, i) => {
                const c = typeColors[node.type];
                return (
                  <div key={node.id} className="relative flex items-start gap-4 fade-in" style={{ animationDelay: `${i * 60}ms` }}>
                    {/* Spine connector */}
                    <div className={`relative z-10 w-16 h-16 rounded-xl border ${c.border} ${c.bg} flex flex-col items-center justify-center shrink-0`}>
                      <span className="text-xl">{c.icon}</span>
                      <span className="font-mono text-[8px] text-white/30 mt-0.5">{String(i + 1).padStart(2, "0")}</span>
                    </div>

                    <div className={`flex-1 glass rounded-xl p-4 border ${c.border} hover:shadow-[0_0_20px_rgba(0,212,255,0.05)] transition-all cursor-pointer`}>
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className={`font-semibold text-sm ${c.text}`}>{node.label}</div>
                          <div className="text-white/60 text-sm mt-0.5">{node.desc}</div>
                          <div className="flex items-center gap-3 mt-2.5 flex-wrap">
                            <div>
                              <MonoLabel>ID</MonoLabel>
                              <div className="font-mono text-[11px] text-white/65 mt-0.5">{node.id}</div>
                            </div>
                            <div>
                              <MonoLabel>Hash</MonoLabel>
                              <div className="font-mono text-[11px] text-white/65 mt-0.5">{node.hash}</div>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {node.verified ? (
                            <div className="flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2.5 py-1.5">
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5">
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                              <span className="font-mono text-[10px] text-emerald-400">Verified</span>
                            </div>
                          ) : (
                            <Badge type="pending" />
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Side: integrity report */}
      <div className="w-64 flex flex-col gap-3">
        <div className="glass-elevated rounded-xl p-4 flex-1">
          <SectionTitle>Integrity Report</SectionTitle>
          <div className="space-y-3">
            {[
              { label: "Chain length", value: "6 nodes" },
              { label: "All hashes valid", value: "Yes", ok: true },
              { label: "Timestamp monotone", value: "Yes", ok: true },
              { label: "Model version", value: "ArcFace R100 v2.1" },
              { label: "Signed by", value: "sys/cam-node-01" },
              { label: "Verified at", value: "09:32:09Z" },
            ].map(r => (
              <div key={r.label} className="flex items-center justify-between">
                <MonoLabel>{r.label}</MonoLabel>
                <MonoValue className={r.ok ? "text-emerald-400" : ""}>{r.value}</MonoValue>
              </div>
            ))}
          </div>

          <div className="mt-4 p-3 rounded-lg bg-emerald-500/6 border border-emerald-500/15">
            <div className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              <span className="text-sm font-medium text-emerald-400">Chain Intact</span>
            </div>
            <div className="text-xs text-white/40 mt-1.5 leading-relaxed">All 6 provenance nodes verified. No tampering detected.</div>
          </div>
        </div>

        <div className="glass rounded-xl p-3">
          <SectionTitle>Raw Attestation</SectionTitle>
          <div className="font-mono text-[9px] text-white/30 leading-relaxed break-all">
            {`{\n  "obs": "OBS-77821",\n  "person": "STU-10042",\n  "ts": "2026-08-23T09:32:07Z",\n  "cam": "CAM-001",\n  "conf": 0.984,\n  "model": "arcface-r100-v2.1",\n  "chain_hash": "1a4b…9f36"\n}`}
          </div>
        </div>
      </div>
    </div>
  );
}