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
