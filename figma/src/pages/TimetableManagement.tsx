// Timetable Management Page - New page built in Figma's design language
// Based on existing frontend's TimetableManagement.vue functionality

import { useState, useEffect, useMemo } from 'react';
import { useTimetableStore } from '@/store';
import type { TimetableEntry, Timetable } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, GlassInput } from '@/components/ui/DesignSystem';

const SESSION_TYPES = ['CLASSROOM', 'BREAK', 'OUTSIDE_LESSON', 'LAB', 'OTHER'] as const;
const DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'] as const;

type SessionType = typeof SESSION_TYPES[number];
type Day = typeof DAYS[number];

export default function TimetableManagement() {
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState<TimetableEntry | null>(null);
  const [formData, setFormData] = useState<Omit<TimetableEntry, 'entry_id' | 'created_at' | 'updated_at'>>({
    person_id: '',
    session_id: '',
    day: 'MONDAY',
    entry_time: 28800, // 08:00
    exit_time: 61200, // 17:00
    entry_window_seconds: 300,
    exit_window_seconds: 300,
    late_tolerance_seconds: 600,
    session_type: 'CLASSROOM',
    subject: '',
    location: '',
    expected_location: '',
    outside_allowed: false,
  });

  const { setEntries: storeSetEntries, setLoading: storeSetLoading, setError: storeSetError } = useTimetableStore();

  // Load mock data on mount
  useEffect(() => {
    if (entries.length === 0) {
      const mockEntries: TimetableEntry[] = [
        {
          entry_id: 'TT-001',
          person_id: 'STU-10042',
          session_id: 'MORNING',
          day: 'MONDAY',
          entry_time: 28800,
          exit_time: 43200,
          entry_window_seconds: 300,
          exit_window_seconds: 300,
          late_tolerance_seconds: 600,
          session_type: 'CLASSROOM',
          subject: 'Mathematics',
          location: 'Room 101',
          expected_location: 'Room 101',
          outside_allowed: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          entry_id: 'TT-002',
          person_id: 'STU-10042',
          session_id: 'AFTERNOON',
          day: 'MONDAY',
          entry_time: 46800,
          exit_time: 61200,
          entry_window_seconds: 300,
          exit_window_seconds: 300,
          late_tolerance_seconds: 600,
          session_type: 'LAB',
          subject: 'Physics Lab',
          location: 'Lab 201',
          expected_location: 'Lab 201',
          outside_allowed: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ];
      setEntries(mockEntries);
      storeSetEntries(mockEntries);
    }
  }, []);

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
    return `${h}:${m}`;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingEntry) {
      const updated = { ...editingEntry, ...formData, updated_at: new Date().toISOString() };
      setEntries(prev => prev.map(e => e.entry_id === editingEntry.entry_id ? updated : e));
      setEditingEntry(null);
    } else {
      const newEntry: TimetableEntry = {
        entry_id: `TT-${Date.now()}`,
        ...formData,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setEntries(prev => [...prev, newEntry]);
    }
    setShowForm(false);
    setFormData({
      person_id: '',
      session_id: '',
      day: 'MONDAY',
      entry_time: 28800,
      exit_time: 61200,
      entry_window_seconds: 300,
      exit_window_seconds: 300,
      late_tolerance_seconds: 600,
      session_type: 'CLASSROOM',
      subject: '',
      location: '',
      expected_location: '',
      outside_allowed: false,
    });
  };

  const handleEdit = (entry: TimetableEntry) => {
    setEditingEntry(entry);
    setFormData(entry);
    setShowForm(true);
  };

  const handleDelete = (entryId: string) => {
    if (confirm('Delete this timetable entry?')) {
      setEntries(prev => prev.filter(e => e.entry_id !== entryId));
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // TODO: Implement Excel import
    alert('Excel import not yet implemented');
  };

  const filteredEntries = useMemo(() => entries, [entries]);

  return (
    <div className="flex h-full flex-col gap-3 p-3 fade-in">
      {/* Header */}
      <div className="glass-elevated rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-base font-semibold text-white/90">Timetable Management</div>
          <div className="text-white/40 text-sm mt-0.5">Manage student schedules and session configurations</div>
        </div>
        <div className="flex gap-2">
          <GlassButton variant="cyan" onClick={() => { setEditingEntry(null); setShowForm(true); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Add Entry
          </GlassButton>
          <label className="glass-btn flex items-center gap-2 h-9 px-3 rounded-lg border text-sm font-medium cursor-pointer">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
            </svg>
            Import Excel
            <input type="file" accept=".xlsx,.xls" onChange={handleImport} className="hidden" />
          </label>
          <GlassButton variant="ghost">Export</GlassButton>
        </div>
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="glass-elevated rounded-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white/90">{editingEntry ? 'Edit Timetable Entry' : 'New Timetable Entry'}</h3>
              <GlassButton variant="ghost" onClick={() => { setShowForm(false); setEditingEntry(null); }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </GlassButton>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Person ID</label>
                  <GlassInput value={formData.person_id} onChange={value => setFormData({...formData, person_id: value})} placeholder="STU-10042" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Session ID</label>
                  <GlassInput value={formData.session_id} onChange={value => setFormData({...formData, session_id: value})} placeholder="MORNING" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Day</label>
                  <select value={formData.day} onChange={e => setFormData({...formData, day: e.target.value as Day})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4">
                    {DAYS.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Session Type</label>
                  <select value={formData.session_type} onChange={e => setFormData({...formData, session_type: e.target.value as SessionType})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4">
                    {SESSION_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Entry Time</label>
                  <input type="time" value={formatTime(formData.entry_time)} onChange={e => setFormData({...formData, entry_time: parseInt(e.target.value.split(':')[0]) * 3600 + parseInt(e.target.value.split(':')[1]) * 60})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Exit Time</label>
                  <input type="time" value={formatTime(formData.exit_time)} onChange={e => setFormData({...formData, exit_time: parseInt(e.target.value.split(':')[0]) * 3600 + parseInt(e.target.value.split(':')[1]) * 60})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Entry Window (sec)</label>
                  <input type="number" value={formData.entry_window_seconds} onChange={e => setFormData({...formData, entry_window_seconds: parseInt(e.target.value)})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Exit Window (sec)</label>
                  <input type="number" value={formData.exit_window_seconds} onChange={e => setFormData({...formData, exit_window_seconds: parseInt(e.target.value)})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" />
                </div>
                <div>
                  <label className="text-[11px] text-white/40 mb-1.5 block">Late Tolerance (sec)</label>
                  <input type="number" value={formData.late_tolerance_seconds} onChange={e => setFormData({...formData, late_tolerance_seconds: parseInt(e.target.value)})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" />
                </div>
                <div className="col-span-2">
                  <label className="text-[11px] text-white/40 mb-1.5 block">Subject</label>
                  <GlassInput value={formData.subject} onChange={value => setFormData({...formData, subject: value})} placeholder="Mathematics" />
                </div>
                <div className="col-span-2">
                  <label className="text-[11px] text-white/40 mb-1.5 block">Location</label>
                  <GlassInput value={formData.location} onChange={value => setFormData({...formData, location: value})} placeholder="Room 101" />
                </div>
                <div className="col-span-2">
                  <label className="text-[11px] text-white/40 mb-1.5 block">Expected Location</label>
                  <GlassInput value={formData.expected_location} onChange={value => setFormData({...formData, expected_location: value})} placeholder="Room 101" />
                </div>
                <div className="col-span-2 flex items-center gap-2">
                  <input type="checkbox" id="outside_allowed" checked={formData.outside_allowed} onChange={e => setFormData({...formData, outside_allowed: e.target.checked})} className="w-4 h-4 rounded border-white/20 bg-white/5 text-cyan-400 focus:ring-cyan-400" />
                  <label htmlFor="outside_allowed" className="text-sm text-white/70">Outside Allowed</label>
                </div>
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <GlassButton variant="ghost" onClick={() => { setShowForm(false); setEditingEntry(null); }}>Cancel</GlassButton>
                <GlassButton variant="cyan" type="submit">{editingEntry ? 'Update' : 'Create'}</GlassButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Entries Table */}
      <div className="flex-1 glass-elevated rounded-xl overflow-hidden flex flex-col">
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-2.5 border-b border-white/6 text-[10px] font-semibold text-white/30 uppercase tracking-wider">
          <span>Person</span>
          <span>Session</span>
          <span>Day</span>
          <span>Time</span>
          <span>Type</span>
          <span>Subject</span>
          <span>Location</span>
          <span>Outside</span>
          <span>Actions</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {filteredEntries.length === 0 ? (
            <div className="flex items-center justify-center h-full text-white/30">
              No timetable entries. Click "Add Entry" to create one.
            </div>
          ) : (
            filteredEntries.map((entry, i) => (
              <div key={entry.entry_id} className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-3 border-b border-white/4 hover:bg-white/3 transition-colors items-center fade-in" style={{ animationDelay: `${i * 30}ms` }}>
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-900/50 to-violet-900/50 border border-white/10 flex items-center justify-center shrink-0">
                    <span className="text-[10px] font-semibold text-white/50">{entry.person_id.slice(-2)}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-white/85 font-medium truncate">{entry.person_id}</div>
                    <MonoLabel>{entry.session_id}</MonoLabel>
                  </div>
                </div>
                <MonoValue>{entry.day}</MonoValue>
                <MonoValue>{formatTime(entry.entry_time)} - {formatTime(entry.exit_time)}</MonoValue>
                <Badge type={entry.session_type.toLowerCase()} />
                <MonoValue className="truncate">{entry.subject}</MonoValue>
                <MonoValue className="truncate">{entry.location}</MonoValue>
                <Badge type={entry.outside_allowed ? 'verified' : 'offline'} />
                <div className="flex gap-1.5">
                  <GlassButton variant="ghost" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleEdit(entry)}>Edit</GlassButton>
                  <GlassButton variant="danger" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleDelete(entry.entry_id)}>Delete</GlassButton>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}