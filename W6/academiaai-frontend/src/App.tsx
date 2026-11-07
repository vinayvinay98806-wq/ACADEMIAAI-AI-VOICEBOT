import { useVoiceCopilot } from './hooks/useVoiceCopilot';
import { Header } from './components/layout/Header';
import { AlertBanner } from './components/layout/AlertBanner';
import { VoiceControlPanel } from './components/voice/VoiceControlPanel';
import { ContextSourcePanel } from './components/context/ContextSourcePanel';
import { TranscriptPanel } from './components/transcript/TranscriptPanel';
import { AIResponsePanel } from './components/transcript/AIResponsePanel';
import { WorkflowTracker } from './components/workflow/WorkflowTracker';
import { PendingActionsList } from './components/approval/PendingActionsList';
import { ActionApprovalModal } from './components/approval/ActionApprovalModal';
import './styles/dashboard.css';

export function App() {
  const {
    voiceState,
    audioLevel,
    startListening,
    pauseListening,
    resumeListening,
    stopListening,
    simulateVoicePrompt,
    connectionStatus,
    toggleConnection,
    reconnect,
    isLoading,
    microphoneStatus,
    screenContext,
    toggleScreenContext,
    academicSources,
    privacyShieldActive,
    togglePrivacyShield,
    transcripts,
    clearTranscripts,
    workflows,
    retryWorkflowStep,
    sensitiveActions,
    selectedAction,
    setSelectedAction,
    approveAction,
    rejectAction,
    notifications,
    dismissNotification,
    addNotification,
    sessionDuration,
  } = useVoiceCopilot();

  // Find latest AI response for the active synthesis panel
  const latestAiResponse = [...transcripts].reverse().find((t) => t.speaker === 'ai');

  const handleTriggerTestAlert = () => {
    addNotification(
      'error',
      'Microphone Buffer Warning',
      'Audio packet latency exceeded 250ms threshold. Adaptive jitter buffer active.',
      () => {
        addNotification('success', 'Jitter Resolved', 'Audio buffer latency normalized to 20ms.');
      },
      'Reset Buffer'
    );
  };

  return (
    <div className="dashboard-root">
      {/* Header bar */}
      <Header
        sessionDuration={sessionDuration}
        connectionStatus={connectionStatus}
        voiceState={voiceState}
        screenContextEnabled={screenContext.captureEnabled}
        toggleConnection={toggleConnection}
        onTriggerTestAlert={handleTriggerTestAlert}
      />

      {/* Global Toast / Alert Banner Stack */}
      <AlertBanner notifications={notifications} onDismiss={dismissNotification} />

      {/* Main 3-Column Responsive Dashboard */}
      <main className="dashboard-grid">
        {/* Left Column: Voice Interaction & Context Grounding */}
        <div className="column-left">
          <VoiceControlPanel
            voiceState={voiceState}
            audioLevel={audioLevel}
            connectionStatus={connectionStatus}
            isLoading={isLoading}
            microphoneStatus={microphoneStatus}
            screenContextEnabled={screenContext.captureEnabled}
            onStartListening={startListening}
            onPauseListening={pauseListening}
            onResumeListening={resumeListening}
            onStopListening={stopListening}
            onSimulatePrompt={simulateVoicePrompt}
            onToggleScreenContext={toggleScreenContext}
            onReconnect={reconnect}
          />

          <ContextSourcePanel
            screenContext={screenContext}
            academicSources={academicSources}
            privacyShieldActive={privacyShieldActive}
            onToggleScreenContext={toggleScreenContext}
            onTogglePrivacyShield={togglePrivacyShield}
            isLoading={isLoading}
          />
        </div>

        {/* Center Column: Live Speech Transcript & AI Synthesis Output */}
        <div className="column-center">
          <TranscriptPanel
            transcripts={transcripts}
            onClear={clearTranscripts}
            isLoading={isLoading}
          />

          <AIResponsePanel
            latestAiResponse={latestAiResponse}
            voiceState={voiceState}
            isLoading={isLoading}
          />
        </div>

        {/* Right Column: Workflow Tracker & Sensitive Action Approvals */}
        <div className="column-right">
          <WorkflowTracker
            workflows={workflows}
            onRetryStep={retryWorkflowStep}
          />

          <PendingActionsList
            actions={sensitiveActions}
            onReviewAction={(action) => setSelectedAction(action)}
          />
        </div>
      </main>

      {/* Sensitive Action Approval Dialog (HITL Safeguard) */}
      {selectedAction && (
        <ActionApprovalModal
          key={selectedAction.id}
          action={selectedAction}
          onClose={() => setSelectedAction(null)}
          onApprove={approveAction}
          onReject={rejectAction}
        />
      )}
    </div>
  );
}

export default App;
