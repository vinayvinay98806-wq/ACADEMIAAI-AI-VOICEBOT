/**
 * AcademiaAI Voice Co-Pilot — Week 2 Frontend & UX Mock-Backend Demonstration
 * Demonstrates:
 * 1. Session Lifecycle: Start -> Pause -> Resume -> Stop
 * 2. Live Transcript Segments: Interim revisions updating in-place -> Final segment
 * 3. Microphone & Screen-Context Capture States (Screen OFF by default, explicit toggle)
 * 4. Grounded Academic Sources catalog
 * 5. Offline resilience and error retry simulation
 */

const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  dim: '\x1b[2m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  red: '\x1b[31m',
};

function logHeader(title) {
  console.log(`\n${colors.bright}${colors.blue}================================================================${colors.reset}`);
  console.log(`${colors.bright}${colors.cyan}  ${title}${colors.reset}`);
  console.log(`${colors.bright}${colors.blue}================================================================${colors.reset}\n`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runDemonstration() {
  logHeader('ACADEMIAAI AI VOICE CO-PILOT — WEEK 2 FRONTEND & UX DEMO');

  // STEP 1: INITIAL STATE (Safe Defaults)
  console.log(`${colors.bright}[STEP 1: INITIAL STATE & SAFE DEFAULTS]${colors.reset}`);
  console.log(`  • Session State:       ${colors.yellow}IDLE${colors.reset}`);
  console.log(`  • Network Gateway:     ${colors.green}CONNECTED (22ms, Mock API Mode)${colors.reset}`);
  console.log(`  • Mic Capture State:   ${colors.dim}STANDBY (Zero audio captured)${colors.reset}`);
  console.log(`  • Screen Context:      ${colors.red}OFF BY DEFAULT${colors.reset} (Privacy Rule: Zero visual frames ingested)`);
  console.log(`  • Privacy Shield:      ${colors.green}ACTIVE${colors.reset} (Student PII redaction filter ready)`);
  await sleep(600);

  // STEP 2: SESSION START & AUDIO CAPTURE
  console.log(`\n${colors.bright}[STEP 2: START VOICE SESSION]${colors.reset}`);
  console.log(`  -> Triggering: startListening()`);
  console.log(`  • Voice State:         ${colors.green}LISTENING${colors.reset}`);
  console.log(`  • Mic Capture Badge:   ${colors.green}LIVE CAPTURE: ON${colors.reset} (Format: PCM 16kHz Mono)`);
  console.log(`  • Audio Level Meter:   ${colors.cyan}68% [||||||||||||||......]${colors.reset}`);
  await sleep(700);

  // STEP 3: PAUSE CONTROLS
  console.log(`\n${colors.bright}[STEP 3: PAUSE VOICE SESSION]${colors.reset}`);
  console.log(`  -> User clicks [Pause]`);
  console.log(`  • Voice State:         ${colors.yellow}PAUSED${colors.reset}`);
  console.log(`  • Mic Capture Badge:   ${colors.yellow}CAPTURE SUSPENDED (PAUSED)${colors.reset}`);
  console.log(`  • Audio Level Meter:   ${colors.dim}0% (Hardware input muted)${colors.reset}`);
  console.log(`  • Session Continuity:  ${colors.green}PRESERVED${colors.reset} (Session not terminated, timer and log intact)`);
  await sleep(700);

  // STEP 4: RESUME CONTROLS
  console.log(`\n${colors.bright}[STEP 4: RESUME VOICE SESSION]${colors.reset}`);
  console.log(`  -> User clicks [Resume]`);
  console.log(`  • Voice State:         ${colors.green}LISTENING${colors.reset}`);
  console.log(`  • Mic Capture Badge:   ${colors.green}LIVE CAPTURE: ON${colors.reset}`);
  console.log(`  • Audio Level Meter:   ${colors.cyan}74% [||||||||||||||||....]${colors.reset}`);
  await sleep(700);

  // STEP 5: LIVE TRANSCRIPT SEGMENTS WITH INTERIM & FINAL REVISIONS
  console.log(`\n${colors.bright}[STEP 5: LIVE TRANSCRIPT STREAM WITH IN-PLACE REVISIONS]${colors.reset}`);
  console.log(`  -> Simulating utterance for stable segment: 'seg-w2-stt-001'`);

  // Interim snapshot 1
  console.log(`  [INTERIM rev 1] [conf: 76%] Speaker: Student (You)`);
  console.log(`    "${colors.yellow}What is the${colors.reset}"`);
  await sleep(500);

  // Interim snapshot 2 (updating segment 'seg-w2-stt-001' in-place)
  console.log(`  [INTERIM rev 2] [conf: 88%] Speaker: Student (You) (in-place revision)`);
  console.log(`    "${colors.yellow}What is the computational complexity of${colors.reset}"`);
  await sleep(500);

  // Final confirmed revision (updating segment 'seg-w2-stt-001' in-place)
  console.log(`  [FINAL   rev 3] [conf: 99%] Speaker: Student (You) (finalized, 0 duplicates)`);
  console.log(`    "${colors.green}What is the computational complexity of self-attention with respect to sequence length?${colors.reset}"`);
  await sleep(700);

  // STEP 6: CONTEXT AND SOURCE GROUNDING
  console.log(`\n${colors.bright}[STEP 6: CONTEXT & SOURCE PANEL DEMONSTRATION]${colors.reset}`);
  console.log(`  -> Initial state check:`);
  console.log(`     • Screen Context:   ${colors.red}OFF${colors.reset} (Co-pilot operating in audio-only mode)`);
  console.log(`  -> User explicitly clicks: [Enable Screen Context (Mock)]`);
  console.log(`     • Screen Context:   ${colors.green}ACTIVE (MOCK SYNTHETIC FIXTURE)${colors.reset}`);
  console.log(`     • Permission:       ${colors.green}Granted (Mock Sandbox)${colors.reset}`);
  console.log(`     • Synthetic Frame:  frame-fixture-014`);
  console.log(`     • Active Window:    CS685_Lecture07_Transformers.pdf`);
  console.log(`     • Grounded Sources: 3 academic citations loaded:`);
  console.log(`       1. Vaswani et al. (2017) "Attention Is All You Need" [Textbook] — 99% match`);
  console.log(`       2. CS 685 Course Syllabus — Module 4 [Syllabus] — 95% match`);
  console.log(`       3. Lecture 7 Slide 14: Multi-Head Scaled Dot-Product [Slide] — 98% match`);
  await sleep(700);

  // STEP 7: AI SYNTHESIS & REASONING RESPONSE
  console.log(`\n${colors.bright}[STEP 7: CO-PILOT SYNTHESIS & REASONING]${colors.reset}`);
  console.log(`  • Voice State:         ${colors.cyan}PROCESSING (Synthesizing with grounded context)${colors.reset}`);
  await sleep(600);
  console.log(`  • Voice State:         ${colors.magenta}RESPONDING${colors.reset}`);
  console.log(`  [AI RESPONSE] Speaker: AcademiaAI Co-Pilot [conf: 99%]`);
  console.log(`    "Standard self-attention computes scaled dot-products between all pairs of N sequence positions,`);
  console.log(`     resulting in O(N² · d) time complexity and O(N²) memory complexity. For long documents, FlashAttention`);
  console.log(`     and causal chunking are commonly used to mitigate this quadratic bottleneck."`);
  await sleep(700);

  // STEP 8: OFFLINE STATE & RETRY BEHAVIOR
  console.log(`\n${colors.bright}[STEP 8: OFFLINE & ERROR RESILIENCE]${colors.reset}`);
  console.log(`  -> Simulating Network Disconnection: toggleConnection() -> OFFLINE`);
  console.log(`     • Network Status:   ${colors.red}OFFLINE${colors.reset}`);
  console.log(`     • Controls Status:  Controls safely disabled to prevent broken submissions`);
  console.log(`     • Alert Banner:     "Connection to AcademiaAI audio stream lost. Backend is offline."`);
  console.log(`     • Retry Button:     [Reconnect Now] rendered in AlertBanner & VoiceControlPanel`);
  await sleep(500);
  console.log(`  -> Triggering: reconnect()`);
  console.log(`     • Reconnecting...`);
  await sleep(400);
  console.log(`     • Network Status:   ${colors.green}ONLINE (Connected, 22ms latency restored)${colors.reset}`);

  // STEP 9: SESSION CLEANUP
  console.log(`\n${colors.bright}[STEP 9: CLEAN SHUTDOWN]${colors.reset}`);
  console.log(`  -> Triggering: stopListening()`);
  console.log(`  • Voice State:         ${colors.dim}IDLE (Session gracefully stopped)${colors.reset}`);
  console.log(`  • Audio Streams:       Closed.`);
  console.log(`\n${colors.green}${colors.bright}DEMONSTRATION COMPLETE: All Week 2 capabilities verified against mock backend.${colors.reset}\n`);
}

runDemonstration().catch(console.error);
