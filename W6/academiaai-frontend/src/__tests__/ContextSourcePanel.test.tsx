import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ContextSourcePanel } from '../components/context/ContextSourcePanel';
import type { ScreenContextData, AcademicSourceReference } from '../types/copilot';

describe('ContextSourcePanel (Week 2 Day 12-13 & Day 14)', () => {
  const defaultScreenContext: ScreenContextData = {
    captureEnabled: false, // Strictly OFF by default
    permission: 'not-requested',
    synthetic: true,
    frameId: 'frame-test-014',
    timestamp: '15:20:00',
    activeWindowTitle: 'CS685_Lecture07_Transformers.pdf',
    ocrExtractedText: 'Attention(Q, K, V) = softmax(QK^T / sqrt(d_k))V',
  };

  const sampleSources: AcademicSourceReference[] = [
    {
      sourceId: 'src-1',
      title: 'Vaswani et al. (2017) "Attention Is All You Need"',
      snippet: '§3.2 Multi-Head Attention equations and matrix projections.',
      uriOrPath: 'arxiv.org/abs/1706.03762',
      relevanceScore: 0.99,
      sourceType: 'textbook',
    },
    {
      sourceId: 'src-2',
      title: 'CS 685 Syllabus Module 4',
      snippet: 'Covers transformer architectures and quadratic sequence limits.',
      uriOrPath: 'canvas.edu/modules/4',
      relevanceScore: 0.94,
      sourceType: 'syllabus',
    },
  ];

  it('renders screen context as OFF by default with clear disabled indicator', () => {
    const onToggle = vi.fn();
    render(
      <ContextSourcePanel
        screenContext={defaultScreenContext}
        academicSources={sampleSources}
        privacyShieldActive={true}
        onToggleScreenContext={onToggle}
        onTogglePrivacyShield={vi.fn()}
      />
    );

    // Indicator must state OFF
    expect(screen.getByText(/Screen Context: OFF/i)).toBeInTheDocument();
    expect(screen.getByText(/Permission:/i)).toBeInTheDocument();
    expect(screen.getByText(/Not Requested \(Default Safe\)/i)).toBeInTheDocument();

    // Clear notice that co-pilot operates strictly in audio-only mode
    expect(screen.getByText(/Screen context is OFF:/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Co-pilot operates strictly in audio-only mode. No window contents, browser tabs, or screen pixels are accessed or transmitted./i)
    ).toBeInTheDocument();

    // Toggle button should offer "Turn ON"
    const toggleBtn = screen.getByRole('button', { name: /toggle screen context\. currently disabled/i });
    expect(toggleBtn).toBeInTheDocument();

    fireEvent.click(toggleBtn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('renders synthetic fixture indicator when screen context is enabled', () => {
    const enabledContext: ScreenContextData = {
      ...defaultScreenContext,
      captureEnabled: true,
      permission: 'granted',
    };

    render(
      <ContextSourcePanel
        screenContext={enabledContext}
        academicSources={sampleSources}
        privacyShieldActive={true}
        onToggleScreenContext={vi.fn()}
        onTogglePrivacyShield={vi.fn()}
      />
    );

    // Must show active with mock label
    expect(screen.getByText(/Screen Context: ON \(Mock\)/i)).toBeInTheDocument();
    expect(screen.getAllByText(/DEMO FIXTURE/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Synthetic Frame/i)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic OCR Extracted Content:/i)).toBeInTheDocument();
    expect(screen.getByText(/Attention\(Q, K, V\)/i)).toBeInTheDocument();

    // Must have option to Turn OFF
    expect(screen.getByRole('button', { name: /toggle screen context\. currently enabled/i })).toBeInTheDocument();
  });

  it('displays grounded academic sources with relevance scores and snippets', () => {
    render(
      <ContextSourcePanel
        screenContext={defaultScreenContext}
        academicSources={sampleSources}
        privacyShieldActive={true}
        onToggleScreenContext={vi.fn()}
        onTogglePrivacyShield={vi.fn()}
      />
    );

    expect(screen.getByText(/Available Academic Sources \(2\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Vaswani et al\. \(2017\) "Attention Is All You Need"/i)).toBeInTheDocument();
    expect(screen.getByText('99% match')).toBeInTheDocument();
    expect(screen.getByText(/CS 685 Syllabus Module 4/i)).toBeInTheDocument();
    expect(screen.getByText('94% match')).toBeInTheDocument();
  });

  it('expands privacy-focused explanation and toggles Academic Privacy Shield', () => {
    const onToggleShield = vi.fn();
    render(
      <ContextSourcePanel
        screenContext={defaultScreenContext}
        academicSources={sampleSources}
        privacyShieldActive={true}
        onToggleScreenContext={vi.fn()}
        onTogglePrivacyShield={onToggleShield}
      />
    );

    const viewPolicyBtn = screen.getByRole('button', { name: /toggle student privacy details/i });
    fireEvent.click(viewPolicyBtn);

    // Points should now be visible
    expect(screen.getByText(/Safe Defaults:/i)).toBeInTheDocument();
    expect(screen.getByText(/No Real Screen Capture:/i)).toBeInTheDocument();
    expect(screen.getByText(/Academic Privacy Shield:/i)).toBeInTheDocument();

    // Toggle switch for privacy shield
    const shieldToggle = screen.getByRole('switch', { name: /toggle academic privacy shield/i });
    expect(shieldToggle).toBeInTheDocument();
    fireEvent.click(shieldToggle);
    expect(onToggleShield).toHaveBeenCalledTimes(1);
  });
});
