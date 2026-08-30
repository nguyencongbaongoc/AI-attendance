// Notification Context - Toast/Alert System
// Replaces alert() and confirm() with proper application notifications

import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

export type NotificationType = 'success' | 'error' | 'warning' | 'info' | 'loading';

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  duration?: number; // ms, 0 = persistent
  action?: {
    label: string;
    onClick: () => void;
  };
  dismissible?: boolean;
}

interface NotificationContextType {
  notifications: Notification[];
  show: (notification: Omit<Notification, 'id'>) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
  success: (title: string, message?: string, duration?: number) => string;
  error: (title: string, message?: string, duration?: number) => string;
  warning: (title: string, message?: string, duration?: number) => string;
  info: (title: string, message?: string, duration?: number) => string;
  loading: (title: string, message?: string) => string;
  confirm: (title: string, message: string, onConfirm: () => void, onCancel?: () => void) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

const generateId = () => Math.random().toString(36).substring(2, 9);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const show = useCallback((notification: Omit<Notification, 'id'>) => {
    const id = generateId();
    const newNotification: Notification = {
      id,
      dismissible: true,
      duration: 5000,
      ...notification,
    };
    
    setNotifications(prev => [...prev, newNotification]);
    
    // Auto-dismiss if duration > 0
    if (newNotification.duration && newNotification.duration > 0) {
      setTimeout(() => {
        setNotifications(prev => prev.filter(n => n.id !== id));
      }, newNotification.duration);
    }
    
    return id;
  }, []);

  const dismiss = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    setNotifications([]);
  }, []);

  const success = useCallback((title: string, message?: string, duration?: number) => {
    return show({ type: 'success', title, message, duration });
  }, [show]);

  const error = useCallback((title: string, message?: string, duration?: number) => {
    return show({ type: 'error', title, message, duration: duration ?? 8000 });
  }, [show]);

  const warning = useCallback((title: string, message?: string, duration?: number) => {
    return show({ type: 'warning', title, message, duration: duration ?? 6000 });
  }, [show]);

  const info = useCallback((title: string, message?: string, duration?: number) => {
    return show({ type: 'info', title, message, duration });
  }, [show]);

  const loading = useCallback((title: string, message?: string) => {
    return show({ type: 'loading', title, message, duration: 0, dismissible: false });
  }, [show]);

  const confirm = useCallback((title: string, message: string, onConfirm: () => void, onCancel?: () => void) => {
    const id = generateId();
    const confirmNotification: Notification = {
      id,
      type: 'warning',
      title,
      message,
      duration: 0,
      dismissible: false,
      action: {
        label: 'Confirm',
        onClick: () => {
          dismiss(id);
          onConfirm();
        },
      },
    };
    
    setNotifications(prev => [...prev, confirmNotification]);
    
    // Store cancel handler
    const cancelHandler = () => {
      dismiss(id);
      onCancel?.();
    };
    
    // We need a way to handle cancel - for now, we'll add a second action
    // This is a simplified version; a full implementation would use a more complex pattern
  }, [dismiss]);

  return (
    <NotificationContext.Provider value={{
      notifications,
      show,
      dismiss,
      dismissAll,
      success,
      error,
      warning,
      info,
      loading,
      confirm,
    }}>
      {children}
      <NotificationContainer notifications={notifications} onDismiss={dismiss} />
    </NotificationContext.Provider>
  );
}

function NotificationContainer({ notifications, onDismiss }: { notifications: Notification[]; onDismiss: (id: string) => void }) {
  if (notifications.length === 0) return null;

  const typeStyles: Record<NotificationType, string> = {
    success: 'border-emerald-500/30 bg-emerald-500/10',
    error: 'border-rose-500/30 bg-rose-500/10',
    warning: 'border-amber-500/30 bg-amber-500/10',
    info: 'border-cyan-500/30 bg-cyan-500/10',
    loading: 'border-violet-500/30 bg-violet-500/10',
  };

  const typeIcons: Record<NotificationType, React.ReactNode> = {
    success: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
    error: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
    ),
    warning: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
    info: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
    ),
    loading: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin">
        <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
        <path d="M12 2a10 10 0 0 1 10 10" strokeOpacity="1" />
      </svg>
    ),
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none" role="region" aria-label="Notifications" aria-live="polite">
      {notifications.map(notification => (
        <div
          key={notification.id}
          className={`pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-xl border min-w-[280px] max-w-[400px] animate-slide-in ${typeStyles[notification.type]}`}
          role="alert"
          aria-live={notification.type === 'error' ? 'assertive' : 'polite'}
        >
          <span className={`flex-shrink-0 text-white/80 ${notification.type === 'loading' ? 'text-violet-400' : notification.type === 'success' ? 'text-emerald-400' : notification.type === 'error' ? 'text-rose-400' : notification.type === 'warning' ? 'text-amber-400' : 'text-cyan-400'}`}>
            {typeIcons[notification.type]}
          </span>
          <div className="flex-1 min-w-0">
            <div className="font-medium text-white/90 text-sm">{notification.title}</div>
            {notification.message && (
              <div className="text-white/60 text-sm mt-0.5">{notification.message}</div>
            )}
            {notification.action && (
              <button
                onClick={notification.action.onClick}
                className="mt-2 text-xs font-medium text-cyan-400 hover:text-cyan-300 underline"
              >
                {notification.action.label}
              </button>
            )}
          </div>
          {notification.dismissible && (
            <button
              onClick={() => onDismiss(notification.id)}
              className="flex-shrink-0 text-white/30 hover:text-white/60 transition-colors p-1"
              aria-label="Dismiss notification"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotifications must be used within a NotificationProvider');
  }
  return context;
}