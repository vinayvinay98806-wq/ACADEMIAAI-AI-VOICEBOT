import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceControlPanel } from '../components/voice/VoiceControlPanel';
import type { VoiceControlPanelProps } from '../components/voice/VoiceControlPanel';

describe('VoiceControlPanel (Week 2 Day 8-9 & Day 14)', () => {
  const defaultMicrophoneStatus = {
    isCapturing: false,
    isPaused: false,
    volumeLevel: 0,
    deviceName: 'Studio Array Mic',
    sampleRate: 16000,
    channels: 1,
    permission: 'granted' as const,
  };

  const createProps = (overrides?: Partial<VoiceControlPanelProps>): VoiceControlPanelProps => ({
    voiceState: 'idle',
    audioLevel: 0,
    connectionStatus: 'connected',
    isLoading: false,
    microphoneStatus: defaultMicrophoneStatus,
    screenContextEnabled: false,
    onStartListening: vi.fn(),
    onPauseListening: vi.fn(),
    onResumeListening: vi.fn(),
    onStopListening: vi.fn(),
    onSimulatePrompt: vi.fn(),
    onToggleScreenContext: vi.fn(),
    onReconnect: vi.fn(),
    ...overrides,
  });

  it('renders idle state with Start button enabled and Pause/Resume inactive', () => {
    const props = createProps({ voiceState: 'idle' });
    render(<VoiceControlPanel {...props} />);

    expect(screen.getByRole('button', { name: /start listening for voice input/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /pause voice session/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resume paused voice session/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /stop current voice session/i })).toBeDisabled();

    // Capture indicator should show Standby
    expect(screen.getAllByText(/STANDBY/i).length).toBeGreaterThan(0);
    // Screen context should show OFF by default
    expect(screen.getByText(/SCREEN CONTEXT:/i)).toBeInTheDocument();
    expect(screen.getByText(/OFF \(DEFAULT\)/i)).toBeInTheDocument();
  });

  it('handles Start button click to trigger onStartListening', () => {
    const props = createProps({ voiceState: 'idle' });
    render(<VoiceControlPanel {...props} />);

    const startBtn = screen.getByRole('button', { name: /start listening for voice input/i });
    fireEvent.click(startBtn);
    expect(props.onStartListening).toHaveBeenCalledTimes(1);
  });

  it('renders active listening state with visible Pause button and LIVE capture indicator', () => {
    const props = createProps({
      voiceState: 'listening',
      audioLevel: 65,
      microphoneStatus: { ...defaultMicrophoneStatus, isCapturing: true, volumeLevel: 65 },
    });
    render(<VoiceControlPanel {...props} />);

    // Pause button must be present and enabled
    const pauseBtn = screen.getByRole('button', { name: /pause voice session without terminating/i });
    expect(pauseBtn).toBeInTheDocument();
    expect(pauseBtn).not.toBeDisabled();

    // Start button should be disabled or indicate Listening...
    expect(screen.getByRole('button', { name: /start listening for voice input/i })).toBeDisabled();

    // Live capture indicator
    expect(screen.getByText(/LIVE/i)).toBeInTheDocument();
    expect(screen.getByText('65%')).toBeInTheDocument();

    // Stop button must be enabled
    expect(screen.getByRole('button', { name: /stop current voice session/i })).not.toBeDisabled();

    // Clicking pause triggers onPauseListening
    fireEvent.click(pauseBtn);
    expect(props.onPauseListening).toHaveBeenCalledTimes(1);
  });

  it('renders paused state with Resume button and suspended capture indicator', () => {
    const props = createProps({
      voiceState: 'paused',
      audioLevel: 0,
      microphoneStatus: { ...defaultMicrophoneStatus, isPaused: true },
    });
    render(<VoiceControlPanel {...props} />);

    // Resume button must be visible and enabled
    const resumeBtn = screen.getByRole('button', { name: /resume paused voice session/i });
    expect(resumeBtn).toBeInTheDocument();
    expect(resumeBtn).not.toBeDisabled();

    // Start button should not be displayed when paused
    expect(screen.queryByRole('button', { name: /start listening for voice input/i })).not.toBeInTheDocument();

    // Capture indicator should display PAUSED
    expect(screen.getAllByText(/PAUSED/i).length).toBeGreaterThan(0);

    // Stop button remains available so user can optionally terminate a paused session
    expect(screen.getByRole('button', { name: /stop current voice session/i })).not.toBeDisabled();

    // Clicking resume triggers onResumeListening
    fireEvent.click(resumeBtn);
    expect(props.onResumeListening).toHaveBeenCalledTimes(1);
  });

  it('handles Stop button click to terminate session', () => {
    const props = createProps({ voiceState: 'listening' });
    render(<VoiceControlPanel {...props} />);

    const stopBtn = screen.getByRole('button', { name: /stop current voice session/i });
    fireEvent.click(stopBtn);
    expect(props.onStopListening).toHaveBeenCalledTimes(1);
  });

  it('renders offline warning and disables listening buttons when connection is lost', () => {
    const props = createProps({
      voiceState: 'idle',
      connectionStatus: 'offline',
    });
    render(<VoiceControlPanel {...props} />);

    // Offline alert visible
    expect(screen.getByText(/Offline Mode:/i)).toBeInTheDocument();
    const reconnectBtn = screen.getByRole('button', { name: /reconnect to audio pipeline/i });
    expect(reconnectBtn).toBeInTheDocument();

    // Start button is disabled while offline
    expect(screen.getByRole('button', { name: /start listening for voice input/i })).toBeDisabled();

    // Clicking reconnect triggers onReconnect
    fireEvent.click(reconnectBtn);
    expect(props.onReconnect).toHaveBeenCalledTimes(1);
  });

  it('renders screen context indicator and toggle action', () => {
    const props = createProps({ screenContextEnabled: false });
    const { rerender } = render(<VoiceControlPanel {...props} />);

    expect(screen.getByText(/OFF \(DEFAULT\)/i)).toBeInTheDocument();
    const toggleBtn = screen.getByRole('button', { name: /toggle screen context/i });
    fireEvent.click(toggleBtn);
    expect(props.onToggleScreenContext).toHaveBeenCalledTimes(1);

    // Rerender when enabled
    rerender(<VoiceControlPanel {...createProps({ screenContextEnabled: true })} />);
    expect(screen.getByText(/ACTIVE \(MOCK\)/i)).toBeInTheDocument();
  });

  it('supports keyboard navigation and accessible ARIA attributes', () => {
    const props = createProps({ voiceState: 'idle' });
    render(<VoiceControlPanel {...props} />);

    const startBtn = screen.getByRole('button', { name: /start listening for voice input/i });
    startBtn.focus();
    expect(startBtn).toHaveFocus();

    const deviceSelect = screen.getByLabelText(/input microphone & audio format/i);
    expect(deviceSelect).toBeInTheDocument();
  });
});
