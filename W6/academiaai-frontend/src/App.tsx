import { useVoiceCopilot } from './hooks/useVoiceCopilot';
import { Header } from './components/layout/Header';
import { AlertBanner } from './components/layout/AlertBanner';
import { VoiceControlPanel } from './components/voice/VoiceControlPanel';
import { PrivacyPanel } from './components/privacy/PrivacyPanel';
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
    stopListening,
    simulateVoicePrompt,
    connectionStatus,
    toggleConnection,
    screenShareStatus,
    toggleScreenShare,
    privacyScope,
    setPrivacyScope,
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
      'Audio packet latency exceeded 250ms threshold. Adaptive jitter buffer active.'
    );
  };

  return (
    <div className="dashboard-root">
      {/* Header bar */}
      <Header
        sessionDuration={sessionDuration}
        connectionStatus={connectionStatus}
        toggleConnection={toggleConnection}
        onTriggerTestAlert={handleTriggerTestAlert}
      />

      {/* Global Toast / Alert Banner Stack */}
      <AlertBanner notifications={notifications} onDismiss={dismissNotification} />

      {/* Main 3-Column Responsive Dashboard */}
      <main className="dashboard-grid">
        {/* Left Column: Voice Interaction & Privacy Controls */}
        <div className="column-left">
          <VoiceControlPanel
            voiceState={voiceState}
            audioLevel={audioLevel}
            onStartListening={startListening}
            onStopListening={stopListening}
            onSimulatePrompt={simulateVoicePrompt}
          />

          <PrivacyPanel
            screenShareStatus={screenShareStatus}
            privacyScope={privacyScope}
            privacyShieldActive={privacyShieldActive}
            onToggleScreenShare={toggleScreenShare}
            onChangeScope={setPrivacyScope}
            onTogglePrivacyShield={togglePrivacyShield}
          />
        </div>

        {/* Center Column: Live Speech Transcript & AI Synthesis Output */}
        <div className="column-center">
          <TranscriptPanel
            transcripts={transcripts}
            onClear={clearTranscripts}
          />

          <AIResponsePanel
            latestAiResponse={latestAiResponse}
            voiceState={voiceState}
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
};

export default App;
