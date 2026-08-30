// Parent/Telegram Page - New page built in Figma's design language
// Based on backend queue/telemetry APIs

import { useState, useEffect, useMemo } from 'react';
import { useParentStore } from '@/store';
import type { Parent, NotificationQueueStats } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, GlassInput, StatusDot } from '@/components/ui/DesignSystem';

export default function ParentTelegram() {
  const [parents, setParents] = useState<Parent[]>([]);
  const [queueStats, setQueueStats] = useState<NotificationQueueStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingParent, setEditingParent] = useState<Parent | null>(null);
  const [formData, setFormData] = useState<Omit<Parent, 'parent_id' | 'created_at' | 'linked_at'> & { telegram_chat_id: string | null; link_code: string | null }>({
    student_id: '',
    name: '',
    phone: '',
    telegram_chat_id: null,
    link_code: null,
  });

  const { setParents: storeSetParents, setQueueStats: storeSetQueueStats } = useParentStore();

  // Load mock data on mount
  useEffect(() => {
    if (parents.length === 0) {
      const mockParents: Parent[] = [
        {
          parent_id: 'PAR-001',
          student_id: 'STU-10042',
          name: 'Aisha Rahman Sr.',
          phone: '+62 812-3456-7890',
          telegram_chat_id: '123456789',
          link_code: 'LINK-ABC123',
          linked_at: '2024-01-15T08:00:00Z',
          created_at: '2024-01-15T08:00:00Z',
        },
        {
          parent_id: 'PAR-002',
          student_id: 'STU-10087',
          name: 'Reza Putra Sr.',
          phone: '+62 813-4567-8901',
          telegram_chat_id: null,
          link_code: 'LINK-DEF456',
          linked_at: null,
          created_at: '2024-01-15T08:00:00Z',
        },
        {
          parent_id: 'PAR-003',
          student_id: 'STU-10033',
          name: 'Mei Ling Sr.',
          phone: '+62 814-5678-9012',
          telegram_chat_id: '987654321',
          link_code: 'LINK-GHI789',
          linked_at: '2024-01-16T08:00:00Z',
          created_at: '2024-01-16T08:00:00Z',
        },
      ];
      setParents(mockParents);
      storeSetParents(mockParents);
      setQueueStats({ pending: 3, sent: 142, failed: 2 });
      storeSetQueueStats({ pending: 3, sent: 142, failed: 2 });
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingParent) {
      const updated = { ...editingParent, ...formData };
      setParents(prev => prev.map(p => p.parent_id === editingParent.parent_id ? updated : p));
      setEditingParent(null);
    } else {
      const newParent: Parent = {
        parent_id: `PAR-${Date.now()}`,
        ...formData,
        linked_at: null,
        created_at: new Date().toISOString(),
      };
      setParents(prev => [...prev, newParent]);
    }
    setShowForm(false);
    setFormData({
      student_id: '',
      name: '',
      phone: '',
      telegram_chat_id: null,
      link_code: null,
    });
  };

  const handleEdit = (parent: Parent) => {
    setEditingParent(parent);
    setFormData({
      student_id: parent.student_id,
      name: parent.name,
      phone: parent.phone,
      telegram_chat_id: parent.telegram_chat_id ?? null,
      link_code: parent.link_code ?? null,
    });
    setShowForm(true);
  };

  const handleDelete = (parentId: string) => {
    if (confirm('Delete this parent record?')) {
      setParents(prev => prev.filter(p => p.parent_id !== parentId));
    }
  };

  const handleLinkTelegram = async (parentId: string) => {
    const linkCode = prompt('Enter Telegram link code:');
    if (!linkCode) return;
    // TODO: Implement link API call
    alert(`Linking parent ${parentId} with code ${linkCode}`);
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3 fade-in">
      {/* Header */}
      <div className="glass-elevated rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-base font-semibold text-white/90">Parent / Telegram Management</div>
          <div className="text-white/40 text-sm mt-0.5">Manage parent records and Telegram notification routing</div>
        </div>
        <div className="flex gap-2">
          <GlassButton variant="cyan" onClick={() => { setEditingParent(null); setShowForm(true); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Add Parent
          </GlassButton>
          <GlassButton variant="ghost" onClick={() => alert('Export not implemented')}>Export</GlassButton>
        </div>
      </div>

      {/* Queue Stats */}
      <div className="glass-elevated rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <SectionTitle>Notification Queue</SectionTitle>
          <GlassButton variant="cyan" className="text-xs" onClick={() => alert('Refresh queue stats')}>Refresh</GlassButton>
        </div>
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "PENDING", value: queueStats?.pending ?? 0, color: "text-amber-400", bg: "bg-amber-500/8 border-amber-500/15" },
            { label: "SENT", value: queueStats?.sent ?? 0, color: "text-emerald-400", bg: "bg-emerald-500/8 border-emerald-500/15" },
            { label: "FAILED", value: queueStats?.failed ?? 0, color: "text-rose-400", bg: "bg-rose-500/8 border-rose-500/15" },
            { label: "TOTAL", value: (queueStats?.pending ?? 0) + (queueStats?.sent ?? 0) + (queueStats?.failed ?? 0), color: "text-white/70", bg: "bg-white/4 border-white/8" },
          ].map(m => (
            <div key={m.label} className={`glass-elevated flex flex-col items-center px-4 py-3 rounded-xl border ${m.bg}`}>
              <span className={`font-mono text-2xl font-bold ${m.color}`}>{m.value}</span>
              <span className="font-mono text-[9px] text-white/30 uppercase tracking-[0.15em] mt-0.5">{m.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="glass-elevated rounded-xl p-6 w-full max-w-md max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white/90">{editingParent ? 'Edit Parent' : 'New Parent'}</h3>
              <GlassButton variant="ghost" onClick={() => { setShowForm(false); setEditingParent(null); }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </GlassButton>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Student ID</label>
                <GlassInput value={formData.student_id} onChange={value => setFormData({...formData, student_id: value})} placeholder="STU-10042" />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Parent Name</label>
                <GlassInput value={formData.name} onChange={value => setFormData({...formData, name: value})} placeholder="John Doe" />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Phone</label>
                <GlassInput value={formData.phone} onChange={value => setFormData({...formData, phone: value})} placeholder="+62 812-3456-7890" />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Telegram Chat ID</label>
                <GlassInput value={formData.telegram_chat_id ?? ''} onChange={value => setFormData({...formData, telegram_chat_id: value})} placeholder="123456789" />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Link Code</label>
                <GlassInput value={formData.link_code ?? ''} onChange={value => setFormData({...formData, link_code: value})} placeholder="LINK-ABC123" />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <GlassButton variant="ghost" onClick={() => { setShowForm(false); setEditingParent(null); }}>Cancel</GlassButton>
                <GlassButton variant="cyan" type="submit">{editingParent ? 'Update' : 'Create'}</GlassButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Parents Table */}
      <div className="flex-1 glass-elevated rounded-xl overflow-hidden flex flex-col">
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-2.5 border-b border-white/6 text-[10px] font-semibold text-white/30 uppercase tracking-wider">
          <span>Parent</span>
          <span>Student</span>
          <span>Phone</span>
          <span>Telegram</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {parents.length === 0 ? (
            <div className="flex items-center justify-center h-full text-white/30">
              No parent records. Click "Add Parent" to create one.
            </div>
          ) : (
            parents.map((parent, i) => (
              <div key={parent.parent_id} className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-3 border-b border-white/4 hover:bg-white/3 transition-colors items-center fade-in" style={{ animationDelay: `${i * 30}ms` }}>
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-900/50 to-amber-900/50 border border-white/10 flex items-center justify-center shrink-0">
                    <span className="text-[10px] font-semibold text-white/50">{parent.name.split(" ").map(n => n[0]).join("").slice(0,2)}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-white/85 font-medium truncate">{parent.name}</div>
                    <MonoLabel>{parent.parent_id}</MonoLabel>
                  </div>
                </div>
                <MonoValue>{parent.student_id}</MonoValue>
                <MonoValue className="truncate">{parent.phone}</MonoValue>
                <div className="flex items-center gap-2">
                  {parent.telegram_chat_id ? (
                    <>
                      <StatusDot status="live" />
                      <MonoValue className="text-emerald-400">Linked</MonoValue>
                    </>
                  ) : (
                    <>
                      <StatusDot status="offline" />
                      <MonoValue className="text-white/40">Not Linked</MonoValue>
                    </>
                  )}
                </div>
                <Badge type={parent.telegram_chat_id ? 'verified' : 'pending'} />
                <div className="flex gap-1.5">
                  <GlassButton variant="ghost" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleEdit(parent)}>Edit</GlassButton>
                  {!parent.telegram_chat_id && (
                    <GlassButton variant="cyan" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleLinkTelegram(parent.parent_id)}>Link</GlassButton>
                  )}
                  <GlassButton variant="danger" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleDelete(parent.parent_id)}>Delete</GlassButton>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}