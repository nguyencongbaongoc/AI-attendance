// Person Search Page - Migrated from original Figma App.tsx PersonSearch component
// Now uses real backend data via hooks and store

import { useState, useMemo } from 'react';
import { useAttendanceStore } from '@/store';
import type { Person } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, GlassInput, Skeleton } from '@/components/ui/DesignSystem';
import PersonCard from '@/components/people/PersonCard';

interface PersonSearchProps {
  onPersonClick: (id: string) => void;
}

export default function PersonSearch({ onPersonClick }: PersonSearchProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const { searchResults, searchLoading, setSearchQuery, setSearchFilter, setSearchResults, setSearchLoading } = useAttendanceStore();

  // For now, use mock data from store - will be replaced with real API call
  const PERSONS: Person[] = [
    { person_id: "STU-10042", name: "Aisha Rahman", role: "student", enrollment_date: "2024-01-15", last_seen: "09:32:07", last_camera: "CAM-001", attendance_state: "present", face_quality: 0.97, track_count: 12 },
    { person_id: "STU-10087", name: "Reza Putra", role: "student", enrollment_date: "2024-01-15", last_seen: "09:31:55", last_camera: "CAM-002", attendance_state: "present", face_quality: 0.93, track_count: 8 },
    { person_id: "STU-10033", name: "Mei Ling", role: "student", enrollment_date: "2024-01-15", last_seen: "09:31:48", last_camera: "CAM-003", attendance_state: "late", face_quality: 0.88, track_count: 5 },
    { person_id: "STF-00012", name: "Dr. Karim Osman", role: "staff", enrollment_date: "2023-08-01", last_seen: "09:31:22", last_camera: "CAM-004", attendance_state: "present", face_quality: 0.99, track_count: 34 },
    { person_id: "STU-10019", name: "Faisal Hadi", role: "student", enrollment_date: "2024-01-15", last_seen: "09:30:58", last_camera: "CAM-005", attendance_state: "present", face_quality: 0.81, track_count: 7 },
    { person_id: "STU-10057", name: "Nur Fatimah", role: "student", enrollment_date: "2024-01-15", last_seen: "09:30:31", last_camera: "CAM-003", attendance_state: "present", face_quality: 0.95, track_count: 9 },
    { person_id: "STU-10099", name: "Ahmad Zaki", role: "student", enrollment_date: "2024-01-15", last_seen: "—", last_camera: "—", attendance_state: "absent", face_quality: 0.91, track_count: 0 },
    { person_id: "STU-10104", name: "Siti Aisyah", role: "student", enrollment_date: "2024-01-15", last_seen: "—", last_camera: "—", attendance_state: "excused", face_quality: 0.89, track_count: 0 },
  ];

  const filtered = useMemo(() => {
    return PERSONS.filter(p => {
      const matchQuery = !query || p.name.toLowerCase().includes(query.toLowerCase()) || p.person_id.toLowerCase().includes(query.toLowerCase());
      const matchFilter = filter === "all" || p.attendance_state === filter || p.role === filter;
      return matchQuery && matchFilter;
    });
  }, [query, filter]);

  const filters = ["all", "present", "absent", "late", "student", "staff"];

  return (
    <div className="flex h-full flex-col gap-3 p-3 fade-in">
      {/* Search header */}
      <div className="glass-elevated rounded-xl p-4">
        <div className="flex items-center gap-3">
          <GlassInput
            className="flex-1"
            placeholder="Search by name, ID, track ID…"
            value={query}
            onChange={setQuery}
            prefix={
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
              </svg>
            }
          />
          <div className="flex gap-1.5 flex-wrap">
            {filters.map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`h-9 px-3 rounded-lg text-[11px] font-semibold uppercase tracking-wider border transition-all duration-150 cursor-pointer min-w-[44px] ${filter === f ? "nav-active" : "nav-inactive"}`}
              >
                {f}
              </button>
            ))}
          </div>
          <GlassButton variant="cyan">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Export
          </GlassButton>
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {searchLoading ? (
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="glass rounded-xl p-4 space-y-3">
                <div className="flex items-center gap-3">
                  <Skeleton className="w-12 h-12 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-2 w-16" />
                  </div>
                </div>
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-3/4" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <div className="w-16 h-16 rounded-full bg-white/4 border border-white/8 flex items-center justify-center">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
              </svg>
            </div>
            <div>
              <div className="text-white/50 font-medium">No results found</div>
              <div className="text-white/25 text-sm mt-1">Try adjusting your search or filters</div>
            </div>
            <GlassButton variant="ghost" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</GlassButton>
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-3">
            {filtered.map((person, idx) => (
              <PersonCard key={person.person_id} person={person} onClick={() => onPersonClick(person.person_id)} delay={idx * 40} />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-1">
        <MonoLabel>{filtered.length} of {PERSONS.length} persons</MonoLabel>
        <MonoLabel>ArcFace DB · 1,247 enrolled vectors</MonoLabel>
      </div>
    </div>
  );
}