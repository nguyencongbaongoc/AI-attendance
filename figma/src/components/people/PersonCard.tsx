// Person Card Component - Preserved from original Figma App.tsx
// Displays person in search results grid

import type { Person } from '@/types/backend';
import { Badge, MonoLabel, MonoValue } from '@/components/ui/DesignSystem';

interface PersonCardProps {
  person: Person;
  onClick?: () => void;
  delay?: number;
}

export default function PersonCard({ person, onClick, delay = 0 }: PersonCardProps) {
  const avatarColors: Record<Person["role"], string> = {
    student: "from-cyan-900/60 to-cyan-800/40",
    staff: "from-violet-900/60 to-violet-800/40",
    visitor: "from-amber-900/60 to-amber-800/40",
    unknown: "from-gray-900/60 to-gray-800/40",
  };

  return (
    <div
      onClick={onClick}
      className="glass rounded-xl p-4 cursor-pointer hover:ring-1 hover:ring-cyan-400/20 hover:shadow-[0_0_20px_rgba(0,212,255,0.06)] transition-all duration-200 fade-in"
      style={{ animationDelay: `${delay}ms` }}
    >
      {/* Avatar placeholder */}
      <div className={`w-14 h-14 rounded-full bg-gradient-to-br ${avatarColors[person.role]} border border-white/10 flex items-center justify-center mb-3`}>
        <span className="text-lg font-semibold text-white/60">{person.name.split(" ").map(n => n[0]).join("").slice(0, 2)}</span>
      </div>

      <div className="font-semibold text-white/90 text-sm leading-tight truncate">{person.name}</div>
      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
        <MonoLabel>{person.person_id}</MonoLabel>
        <Badge type={person.role} />
      </div>

      <div className="mt-3 space-y-1.5">
        <div className="flex items-center justify-between">
          <MonoLabel>Status</MonoLabel>
          <Badge type={person.attendance_state} />
        </div>
        <div className="flex items-center justify-between">
          <MonoLabel>Face quality</MonoLabel>
          <MonoValue>{Math.round(person.face_quality * 100)}%</MonoValue>
        </div>
        <div className="flex items-center justify-between">
          <MonoLabel>Last seen</MonoLabel>
          <MonoValue className="text-white/50">{person.last_seen}</MonoValue>
        </div>
      </div>
    </div>
  );
}