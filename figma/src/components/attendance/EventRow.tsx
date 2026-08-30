// Event Row Component - Preserved from original Figma App.tsx
// Displays attendance event in the live events timeline

import type { AttendanceEvent } from '@/types/backend';
import { StatusDot, Badge, MonoLabel, MonoValue } from '@/components/ui/DesignSystem';

interface EventRowProps {
  event: AttendanceEvent;
  onClick?: () => void;
}

export default function EventRow({ event, onClick }: EventRowProps) {
  return (
    <div
      onClick={onClick}
      className="group flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/4 cursor-pointer transition-all duration-150 border border-transparent hover:border-white/6"
    >
      <StatusDot status={event.type === "enter" ? "present" : event.type === "exit" ? "absent" : "offline"} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-white/85 font-medium truncate">{event.personName}</span>
          <Badge type={event.type} />
        </div>
        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
          <MonoLabel>{event.personId}</MonoLabel>
          <span className="text-white/15">·</span>
          <MonoLabel>{event.cameraId}</MonoLabel>
          <span className="text-white/15">·</span>
          <MonoLabel>{event.trackId}</MonoLabel>
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="font-mono text-[11px] text-white/60">{event.timestamp}</div>
        <div className="font-mono text-[10px] text-white/30 mt-0.5">{(event.confidence * 100).toFixed(1)}%</div>
      </div>
    </div>
  );
}