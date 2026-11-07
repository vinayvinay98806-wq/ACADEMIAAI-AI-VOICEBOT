import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Header } from '../components/layout/Header';
import { AlertBanner } from '../components/layout/AlertBanner';
import type { SystemNotification } from '../types/copilot';

describe('Header & AlertBanner Components', () => {
  it('renders Header with session duration and capture indicators', () => {
    const toggleConnMock = vi.fn();
    const alertMock = vi.fn();

    render(
      <Header
        sessionDuration="00:23:40"
        connectionStatus="connected"
        voiceState="listening"
        screenContextEnabled={false}
        toggleConnection={toggleConnMock}
        onTriggerTestAlert={alertMock}
      />
    );

    expect(screen.getByText('00:23:40')).toBeInTheDocument();
    expect(screen.getByText(/Online \(22ms\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Mic: LIVE/i)).toBeInTheDocument();
    expect(screen.getByText(/Screen: OFF/i)).toBeInTheDocument();

    const connBtn = screen.getByRole('button', { name: /connection status: connected/i });
    fireEvent.click(connBtn);
    expect(toggleConnMock).toHaveBeenCalledTimes(1);

    const alertBtn = screen.getByRole('button', { name: /simulate test alert/i });
    fireEvent.click(alertBtn);
    expect(alertMock).toHaveBeenCalledTimes(1);
  });

  it('renders AlertBanner with error notification and triggers retry action', () => {
    const retryMock = vi.fn();
    const dismissMock = vi.fn();

    const notifications: SystemNotification[] = [
      {
        id: 'notif-err-1',
        type: 'error',
        title: 'Network Timeout',
        message: 'Speech packet transmission timed out.',
        timestamp: '15:22:00',
        retryAction: retryMock,
        retryLabel: 'Retry Packet',
      },
    ];

    render(<AlertBanner notifications={notifications} onDismiss={dismissMock} />);

    expect(screen.getByText('Network Timeout')).toBeInTheDocument();
    expect(screen.getByText('Speech packet transmission timed out.')).toBeInTheDocument();

    const retryBtn = screen.getByRole('button', { name: /retry action: retry packet/i });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(retryMock).toHaveBeenCalledTimes(1);
    expect(dismissMock).toHaveBeenCalledWith('notif-err-1');
  });

  it('dismisses notification when dismiss button is clicked', () => {
    const dismissMock = vi.fn();
    const notifications: SystemNotification[] = [
      {
        id: 'notif-info-1',
        type: 'info',
        title: 'Microphone Calibrated',
        message: 'Gain levels optimized.',
        timestamp: '15:20:00',
      },
    ];

    render(<AlertBanner notifications={notifications} onDismiss={dismissMock} />);

    const dismissBtn = screen.getByRole('button', { name: /dismiss notification: microphone calibrated/i });
    fireEvent.click(dismissBtn);
    expect(dismissMock).toHaveBeenCalledWith('notif-info-1');
  });
});
