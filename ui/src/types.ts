export interface Task {
  id: string;
  name: string;
  description: string;
  status: 'pending' | 'in-progress' | 'completed' | 'failed';
  priority: number;
  deps: string[];
  gates: string[];
}

export interface TaskQueue {
  tasks: Task[];
  progress: {
    completed: number;
    inProgress: number;
    pending: number;
    failed: number;
  };
}

export interface GanSummary {
  finalScore: number;
  passed: boolean;
  iterations: number;
  scores: number[];
  elapsed: string;
}

export interface GateStatus {
  [key: string]: 'pass' | 'fail' | 'pending';
}

export interface HarnessState {
  taskQueue: TaskQueue | null;
  ganSummary: GanSummary | null;
  gateStatus: GateStatus;
  running: boolean;
  startedAt: string | null;
}

// ─── Test Execution Engine Types ───────────────────────────────────────────────

export type TestStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'cancelled';

export interface TestResult {
  id: string;
  name: string;
  status: TestStatus;
  duration: number;
  error?: string;
  logs: TestLogEntry[];
}

export interface TestLogEntry {
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug' | 'output';
  message: string;
  raw?: string;
}

export interface TestSuite {
  id: string;
  name: string;
  tests: TestResult[];
  status: TestStatus;
  startTime: string | null;
  endTime: string | null;
  totalTests: number;
  passed: number;
  failed: number;
  skipped: number;
  duration: number;
}

export interface RunConfig {
  suites: string[];
  parallel: boolean;
  maxWorkers: number;
  retryFailed: boolean;
  maxRetries: number;
  timeout: number;
  verbose: boolean;
}

export interface ExecutionProgress {
  totalSuites: number;
  completedSuites: number;
  totalTests: number;
  passedTests: number;
  failedTests: number;
  skippedTests: number;
  currentSuite: string | null;
  currentTest: string | null;
  startTime: string;
  eta: number | null;
  elapsed: number;
  isRunning: boolean;
  isCancelled: boolean;
}

export type ExecutionEventType = 'suite-start' | 'suite-complete' | 'test-start' | 'test-complete' | 'output' | 'error' | 'complete' | 'cancelled';

export interface ExecutionEvent {
  type: ExecutionEventType;
  suiteId?: string;
  testId?: string;
  data?: TestSuite | TestResult | TestLogEntry | string;
  progress?: Partial<ExecutionProgress>;
}
