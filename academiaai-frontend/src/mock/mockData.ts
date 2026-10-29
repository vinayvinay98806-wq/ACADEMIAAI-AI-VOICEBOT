import type {
  TranscriptItem,
  Workflow,
  SensitiveAction,
  SystemNotification,
} from '../types/copilot';

export const INITIAL_TRANSCRIPTS: TranscriptItem[] = [
  {
    id: 'tx-1',
    speaker: 'system',
    text: 'AcademiaAI Voice Co-Pilot connected. Session initialized with Academic Context: CS 685 (Deep Learning & NLP).',
    timestamp: '15:20:00',
  },
  {
    id: 'tx-2',
    speaker: 'user',
    text: 'Can you summarize slide 14 on Multi-Head Self-Attention and highlight how query, key, and value vectors interact?',
    timestamp: '15:21:12',
    confidence: 0.98,
  },
  {
    id: 'tx-3',
    speaker: 'ai',
    text: 'In slide 14, Multi-Head Self-Attention computes attention weights by scaling the dot product of Query (Q) and Key (K) vectors by 1/sqrt(d_k), then applying Softmax before taking a weighted sum of Value (V) vectors. Running this across multiple heads allows the model to jointly attend to information from different representation subspaces.',
    timestamp: '15:21:16',
    confidence: 0.96,
  },
];

export const INITIAL_WORKFLOWS: Workflow[] = [
  {
    id: 'wf-1',
    title: 'Lecture 7: Multi-Head Attention Synthesis',
    category: 'Study Aid Pipeline',
    status: 'in-progress',
    currentStepIndex: 2,
    steps: [
      {
        id: 's1',
        title: 'Screen Capture Slide Ingestion',
        description: 'Extract slide OCR text and mathematical formulas from active viewport',
        status: 'completed',
        duration: '1.2s',
      },
      {
        id: 's2',
        title: 'Formula & Diagram Parsing',
        description: 'Verify LaTeX equation syntax for scaled dot-product attention',
        status: 'completed',
        duration: '2.4s',
      },
      {
        id: 's3',
        title: 'Concept Graph Alignment',
        description: 'Connecting multi-head projections with syllabus topic 4.2',
        status: 'running',
        duration: 'Running...',
      },
      {
        id: 's4',
        title: 'Practice Question Generation',
        description: 'Generate 3 self-test questions with solution rationales',
        status: 'pending',
      },
      {
        id: 's5',
        title: 'Sync to Personal Study Binder',
        description: 'Save synthesized markdown summary to user repository',
        status: 'pending',
      },
    ],
  },
  {
    id: 'wf-2',
    title: 'Citation & Reference Verification',
    category: 'Academic Integrity',
    status: 'failed',
    currentStepIndex: 1,
    steps: [
      {
        id: 'c1',
        title: 'Extract In-Text Citations',
        description: 'Identify Vaswani et al. (2017) and Devlin et al. (2018) in drafted paper',
        status: 'completed',
        duration: '0.8s',
      },
      {
        id: 'c2',
        title: 'CrossRef / Semantic Scholar DOI Lookup',
        description: 'Check active DOI links for Devlin et al. citation',
        status: 'failed',
        duration: '3.1s',
        errorDetails: 'DOI resolution timeout: Provider server rate limited. Click Retry to re-query repository.',
      },
      {
        id: 'c3',
        title: 'Format BibTeX References',
        description: 'Format bibliography according to IEEE conference standards',
        status: 'pending',
      },
    ],
  },
];

export const INITIAL_SENSITIVE_ACTIONS: SensitiveAction[] = [
  {
    id: 'act-101',
    title: 'Submit Assignment Draft to Canvas LMS',
    description: 'Upload current working draft "NLP_Assignment2_v4.pdf" directly to Course Canvas LMS portal under your student account.',
    impact: 'Replaces previous submission. Timestamp recorded as official grading entry.',
    riskLevel: 'high',
    targetSystem: 'Canvas LMS (API Gateway)',
    parameters: {
      'Course': 'CS 685: Advanced NLP',
      'Assignment ID': 'HW-02-Transformer-Attention',
      'File Name': 'NLP_Assignment2_v4.pdf',
      'Student ID': 'STU-2026-8819 (Masked)',
    },
    status: 'pending',
    timestamp: '15:23:45',
  },
  {
    id: 'act-102',
    title: 'Email Office Hours Question to Professor',
    description: 'Dispatch auto-drafted email with attached code snippet query regarding attention mask dimensional mismatch.',
    impact: 'Sends formal email notification directly to Prof. Reynolds and TAs.',
    riskLevel: 'medium',
    targetSystem: 'Academia Institutional Mailer',
    parameters: {
      'Recipient': 'reynolds.nlp@university.edu',
      'Subject': '[CS 685] Question regarding Assignment 2 Attention Mask Dimension',
      'Attachments': 'mask_debug.py',
    },
    status: 'pending',
    timestamp: '15:25:10',
  },
];

export const SAMPLE_VOICE_PROMPTS = [
  {
    label: 'Summarize Lecture Slide',
    query: 'Summarize the core takeaways of the current slide and explain the computational complexity.',
  },
  {
    label: 'Generate Practice Questions',
    query: 'Generate three multiple-choice practice questions on self-attention mechanisms with answer keys.',
  },
  {
    label: 'Submit Draft to Canvas [Sensitive]',
    query: 'Please submit my completed assignment draft "NLP_Assignment2_v4.pdf" to Canvas LMS.',
    triggersAction: true,
  },
  {
    label: 'Check Citation Validity',
    query: 'Cross-check the citations in my draft paper against Semantic Scholar for DOI accuracy.',
  },
];

export const INITIAL_NOTIFICATIONS: SystemNotification[] = [
  {
    id: 'notif-1',
    type: 'info',
    title: 'Session Ready',
    message: 'Audio input detected at 48kHz. Privacy Shield is active; screen OCR will redact confidential student data.',
    timestamp: '15:20:00',
  },
];

