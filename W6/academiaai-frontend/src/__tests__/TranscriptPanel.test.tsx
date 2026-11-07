import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TranscriptPanel } from '../components/transcript/TranscriptPanel';
import type { TranscriptItem } from '../types/copilot';

describe('TranscriptPanel (Week 2 Day 10-11 & Day 14)', () => {
  beforeEach(() => {
    // Mock scrollIntoView in jsdom
    Element.prototype.scrollIntoView = vi.fn();
  });

  const sampleInterimItem: TranscriptItem = {
    id: 'seg-101',
    speaker: 'user',
    speakerId: 'Student (You)',
    text: 'What is the computational complexity of',
    timestamp: '15:24:00',
    startTime: 0.0,
    endTime: 1.2,
    confidence: 0.85,
    isFinal: false,
    revisionCount: 1,
  };

  const sampleFinalItem: TranscriptItem = {
    id: 'seg-101',
    speaker: 'user',
    speakerId: 'Student (You)',
    text: 'What is the computational complexity of self-attention?',
    timestamp: '15:24:02',
    startTime: 0.0,
    endTime: 2.1,
    confidence: 0.98,
    isFinal: true,
    revisionCount: 2,
  };

  it('renders empty state when transcripts list is empty', () => {
    render(<TranscriptPanel transcripts={[]} onClear={vi.fn()} />);
    expect(screen.getByText(/no active speech transcript yet/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy full transcript/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /clear current transcript/i })).toBeDisabled();
  });

  it('visibly distinguishes interim segments from final segments', () => {
    const { container } = render(
      <TranscriptPanel transcripts={[sampleInterimItem]} onClear={vi.fn()} />
    );

    // Interim indicator pill
    expect(screen.getByText(/Interim/i)).toBeInTheDocument();
    const interimBubble = container.querySelector('.segment-interim');
    expect(interimBubble).toBeInTheDocument();

    // Confidence displayed with medium threshold
    expect(screen.getByText('85% match')).toBeInTheDocument();
    expect(container.querySelector('.conf-med')).toBeInTheDocument();

    // Stream offset displayed
    expect(screen.getByText(/\+0.0s/i)).toBeInTheDocument();
  });

  it('updates the corresponding segment in-place when a final revision arrives instead of duplicating it', () => {
    const onClear = vi.fn();
    const { rerender, container } = render(
      <TranscriptPanel transcripts={[sampleInterimItem]} onClear={onClear} />
    );

    expect(screen.getByText(/What is the computational complexity of$/i)).toBeInTheDocument();
    let bubbles = container.querySelectorAll('.transcript-bubble');
    expect(bubbles.length).toBe(1);

    // Simulate final revision arrival for the same segment_id ('seg-101')
    rerender(<TranscriptPanel transcripts={[sampleFinalItem]} onClear={onClear} />);

    // Must still have exactly 1 segment (NOT duplicated!)
    bubbles = container.querySelectorAll('.transcript-bubble');
    expect(bubbles.length).toBe(1);

    // Updated content
    expect(screen.getByText(/What is the computational complexity of self-attention\?/i)).toBeInTheDocument();

    // Changed to Final
    expect(screen.getByText(/Final/i)).toBeInTheDocument();
    expect(container.querySelector('.segment-final')).toBeInTheDocument();
    expect(screen.getByText('98% match')).toBeInTheDocument();
    expect(container.querySelector('.conf-high')).toBeInTheDocument();

    // Revision pill shows rev 2
    expect(screen.getByText('rev 2')).toBeInTheDocument();
  });

  it('renders low confidence scores with rose indicator class', () => {
    const lowConfItem: TranscriptItem = {
      id: 'seg-low',
      speaker: 'user',
      text: 'Noisy audio chunk',
      timestamp: '15:25:00',
      confidence: 0.62,
      isFinal: true,
    };

    const { container } = render(
      <TranscriptPanel transcripts={[lowConfItem]} onClear={vi.fn()} />
    );

    expect(screen.getByText('62% match')).toBeInTheDocument();
    expect(container.querySelector('.conf-low')).toBeInTheDocument();
  });

  it('displays speaker information supplied by schema', () => {
    const items: TranscriptItem[] = [
      {
        id: 'tx-user',
        speaker: 'user',
        speakerId: 'Priya A (Presenter)',
        text: 'Starting query...',
        timestamp: '15:26:00',
        isFinal: true,
      },
      {
        id: 'tx-ai',
        speaker: 'ai',
        speakerId: 'AcademiaAI Reasoning Engine',
        text: 'Processing context...',
        timestamp: '15:26:02',
        isFinal: true,
      },
    ];

    render(<TranscriptPanel transcripts={items} onClear={vi.fn()} />);

    expect(screen.getByText('Priya A (Presenter)')).toBeInTheDocument();
    expect(screen.getByText('AcademiaAI Reasoning Engine')).toBeInTheDocument();
  });

  it('handles copy and clear actions', () => {
    // Mock navigator.clipboard
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const onClearMock = vi.fn();
    render(<TranscriptPanel transcripts={[sampleFinalItem]} onClear={onClearMock} />);

    const copyBtn = screen.getByRole('button', { name: /copy full transcript/i });
    fireEvent.click(copyBtn);
    expect(writeTextMock).toHaveBeenCalledTimes(1);

    const clearBtn = screen.getByRole('button', { name: /clear current transcript/i });
    fireEvent.click(clearBtn);
    expect(onClearMock).toHaveBeenCalledTimes(1);
  });
});
