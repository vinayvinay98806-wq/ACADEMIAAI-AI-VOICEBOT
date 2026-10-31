import React from 'react';
import type { SystemNotification } from '../../types/copilot';

interface AlertBannerProps {
  notifications: SystemNotification[];
  onDismiss: (id: string) => void;
}

export const AlertBanner: React.FC<AlertBannerProps> = ({ notifications, onDismiss }) => {
  if (notifications.length === 0) return null;

  return (
    <div className="alert-stack" role="region" aria-label="System notifications">
      {notifications.map((notif) => (
        <div
          key={notif.id}
          className={`alert-item alert-${notif.type}`}
          role={notif.type === 'error' ? 'alert' : 'status'}
          aria-live="polite"
        >
          <div className="alert-icon" aria-hidden="true">
            {notif.type === 'error' && (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            )}
            {notif.type === 'warning' && (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            )}
            {notif.type === 'success' && (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            )}
            {notif.type === 'info' && (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            )}
          </div>
          <div className="alert-content">
            <span className="alert-title">{notif.title}</span>
            <p className="alert-message">{notif.message}</p>
          </div>
          <span className="alert-time">{notif.timestamp}</span>
          <button
            type="button"
            className="alert-dismiss"
            onClick={() => onDismiss(notif.id)}
            aria-label={`Dismiss notification: ${notif.title}`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
};

