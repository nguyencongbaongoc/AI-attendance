// Excel Export Page - New page built in Figma's design language
// Based on existing frontend's DailyExcelExporter functionality

import { useState, useEffect } from 'react';
import { useExcelStore } from '@/store';
import type { DailyExportRequest, DailyExportResult } from '@/types/backend';
import { Badge, MonoLabel, MonoValue, SectionTitle, GlassButton, GlassInput } from '@/components/ui/DesignSystem';

export default function ExcelExport() {
  const [exports, setExports] = useState<DailyExportResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showExportForm, setShowExportForm] = useState(false);
  const [formData, setFormData] = useState<DailyExportRequest>({
    date: new Date().toISOString().split('T')[0],
    timezone: 'Asia/Bangkok',
    export_version: '1.0',
    include_events_sheet: true,
    include_provenance_sheet: true,
    include_summary_sheet: true,
  });

  const { setExports: storeSetExports, setLoading: storeSetLoading, setError: storeSetError } = useExcelStore();

  // Load mock data on mount
  useEffect(() => {
    if (exports.length === 0) {
      const mockExports: DailyExportResult[] = [
        {
          export_id: 'EXP-20260823-001',
          file_path: '/exports/daily_20260823.xlsx',
          sheets_created: ['Daily Attendance', 'Events', 'Provenance', 'Summary'],
          record_count: 241,
          success: true,
          created_at: '2026-08-23T10:00:00Z',
        },
        {
          export_id: 'EXP-20260822-001',
          file_path: '/exports/daily_20260822.xlsx',
          sheets_created: ['Daily Attendance', 'Events', 'Provenance', 'Summary'],
          record_count: 238,
          success: true,
          created_at: '2026-08-22T10:00:00Z',
        },
        {
          export_id: 'EXP-20260821-001',
          file_path: '/exports/daily_20260821.xlsx',
          sheets_created: ['Daily Attendance', 'Events', 'Provenance', 'Summary'],
          record_count: 245,
          success: true,
          created_at: '2026-08-21T10:00:00Z',
        },
      ];
      setExports(mockExports);
      storeSetExports(mockExports);
    }
  }, []);

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      // TODO: Implement actual API call
      // const result = await exportDailyAttendance(formData);

      // Mock result
      const newExport: DailyExportResult = {
        export_id: `EXP-${formData.date.replace(/-/g, '')}-${Date.now().toString().slice(-3)}`,
        file_path: `/exports/daily_${formData.date.replace(/-/g, '')}.xlsx`,
        sheets_created: [
          'Daily Attendance',
          ...(formData.include_events_sheet ? ['Events'] : []),
          ...(formData.include_provenance_sheet ? ['Provenance'] : []),
          ...(formData.include_summary_sheet ? ['Summary'] : []),
        ],
        record_count: Math.floor(Math.random() * 50) + 200,
        success: true,
        created_at: new Date().toISOString(),
      };

      setExports(prev => [newExport, ...prev]);
      storeSetExports([newExport, ...exports]);
      setShowExportForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (exportId: string) => {
    // TODO: Implement actual download
    alert(`Downloading export ${exportId}`);
  };

  const handleDelete = (exportId: string) => {
    if (confirm('Delete this export record?')) {
      setExports(prev => prev.filter(e => e.export_id !== exportId));
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3 fade-in">
      {/* Header */}
      <div className="glass-elevated rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-base font-semibold text-white/90">Excel Export Management</div>
          <div className="text-white/40 text-sm mt-0.5">Generate and manage daily attendance Excel exports</div>
        </div>
        <div className="flex gap-2">
          <GlassButton variant="cyan" onClick={() => setShowExportForm(true)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            New Export
          </GlassButton>
        </div>
      </div>

      {/* Export Form Modal */}
      {showExportForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="glass-elevated rounded-xl p-6 w-full max-w-md max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white/90">Generate Daily Export</h3>
              <GlassButton variant="ghost" onClick={() => setShowExportForm(false)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </GlassButton>
            </div>
            <form onSubmit={handleExport} className="space-y-4">
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Date</label>
                <input type="date" value={formData.date} onChange={e => setFormData({...formData, date: e.target.value})} className="w-full h-11 rounded-lg bg-white/5 border border-white/10 text-white/90 placeholder-white/25 text-sm font-ui transition-all duration-200 outline-none focus:border-cyan-500/40 focus:bg-white/8 focus:shadow-[0_0_0_2px_rgba(0,212,255,0.08)] px-4" required />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Timezone</label>
                <GlassInput value={formData.timezone} onChange={value => setFormData({...formData, timezone: value})} placeholder="Asia/Bangkok" />
              </div>
              <div>
                <label className="text-[11px] text-white/40 mb-1.5 block">Export Version</label>
                <GlassInput value={formData.export_version} onChange={value => setFormData({...formData, export_version: value})} placeholder="1.0" />
              </div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={formData.include_events_sheet} onChange={e => setFormData({...formData, include_events_sheet: e.target.checked})} className="w-4 h-4 rounded border-white/20 bg-white/5 text-cyan-400 focus:ring-cyan-400" />
                  <span className="text-sm text-white/70">Include Events Sheet</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={formData.include_provenance_sheet} onChange={e => setFormData({...formData, include_provenance_sheet: e.target.checked})} className="w-4 h-4 rounded border-white/20 bg-white/5 text-cyan-400 focus:ring-cyan-400" />
                  <span className="text-sm text-white/70">Include Provenance Sheet</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={formData.include_summary_sheet} onChange={e => setFormData({...formData, include_summary_sheet: e.target.checked})} className="w-4 h-4 rounded border-white/20 bg-white/5 text-cyan-400 focus:ring-cyan-400" />
                  <span className="text-sm text-white/70">Include Summary Sheet</span>
                </label>
              </div>
              {error && (
                <div className="text-rose-400 text-sm p-2 bg-rose-500/10 border border-rose-500/20 rounded">
                  {error}
                </div>
              )}
              <div className="flex gap-2 justify-end mt-4">
                <GlassButton variant="ghost" onClick={() => setShowExportForm(false)}>Cancel</GlassButton>
                <GlassButton variant="cyan" type="submit" disabled={loading}>
                  {loading ? 'Generating...' : 'Generate Export'}
                </GlassButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Exports Table */}
      <div className="flex-1 glass-elevated rounded-xl overflow-hidden flex flex-col">
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-2.5 border-b border-white/6 text-[10px] font-semibold text-white/30 uppercase tracking-wider">
          <span>Export ID</span>
          <span>Date</span>
          <span>Records</span>
          <span>Sheets</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {exports.length === 0 ? (
            <div className="flex items-center justify-center h-full text-white/30">
              No exports generated yet. Click "New Export" to create one.
            </div>
          ) : (
            exports.map((exp, i) => (
              <div key={exp.export_id} className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-3 border-b border-white/4 hover:bg-white/3 transition-colors items-center fade-in" style={{ animationDelay: `${i * 30}ms` }}>
                <div className="min-w-0">
                  <div className="font-mono text-[11px] text-white/80 truncate">{exp.export_id}</div>
                  <MonoValue className="text-white/40">{exp.file_path}</MonoValue>
                </div>
                <MonoValue>{exp.created_at.split('T')[0]}</MonoValue>
                <MonoValue>{exp.record_count}</MonoValue>
                <MonoValue>{exp.sheets_created.length}</MonoValue>
                <Badge type={exp.success ? 'verified' : 'flagged'} />
                <div className="flex gap-1.5">
                  <GlassButton variant="ghost" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleDownload(exp.export_id)}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                  </GlassButton>
                  <GlassButton variant="danger" className="h-7 min-h-0 px-2 text-[11px]" onClick={() => handleDelete(exp.export_id)}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  </GlassButton>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}