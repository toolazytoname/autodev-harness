import { useState, useEffect, useCallback } from 'react';
import type { TaskQueue, GanSummary, GateStatus, HarnessState } from '../types';

const AUTODEV_PATH = './autodev-harness';

export function useHarnessData(refreshInterval = 5000) {
  const [state, setState] = useState<HarnessState>({
    taskQueue: null,
    ganSummary: null,
    gateStatus: {},
    running: false,
    startedAt: null,
  });

  const fetchData = useCallback(async () => {
    try {
      // In a real implementation, this would fetch from the local API
      // For now, we'll simulate the data structure
      const data = await fetchHarnessData();
      setState(prev => ({ ...prev, ...data }));
    } catch (error) {
      console.error('Failed to fetch harness data:', error);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  return state;
}

async function fetchHarnessData(): Promise<Partial<HarnessState>> {
  // This would be replaced with actual API calls in production
  // For demo, return simulated data
  
  const taskQueue: TaskQueue = {
    tasks: [
      { id: 'task-001', name: 'Project setup', status: 'completed', priority: 1, deps: [], gates: ['lint', 'build'], description: '' },
      { id: 'task-002', name: 'Authentication', status: 'completed', priority: 2, deps: ['task-001'], gates: ['lint', 'build', 'test'], description: '' },
      { id: 'task-003', name: 'Dashboard UI', status: 'in-progress', priority: 3, deps: ['task-001'], gates: ['lint', 'build'], description: '' },
      { id: 'task-004', name: 'API endpoints', status: 'pending', priority: 4, deps: ['task-002'], gates: ['lint', 'build', 'test'], description: '' },
      { id: 'task-005', name: 'User management', status: 'pending', priority: 5, deps: ['task-002'], gates: ['lint', 'build', 'test'], description: '' },
    ],
    progress: { completed: 2, inProgress: 1, pending: 2, failed: 0 },
  };

  const ganSummary: GanSummary = {
    finalScore: 7.2,
    passed: true,
    iterations: 3,
    scores: [5.1, 6.4, 7.2],
    elapsed: '45m 23s',
  };

  const gateStatus: GateStatus = {
    lint: 'pass',
    build: 'pass',
    test: 'pass',
    e2e: 'pending',
    security: 'pass',
  };

  return {
    taskQueue,
    ganSummary,
    gateStatus,
    running: true,
    startedAt: new Date().toISOString(),
  };
}

export function useStartHarness() {
  const [loading, setLoading] = useState(false);
  
  const start = async (brief: string) => {
    setLoading(true);
    try {
      // In production, this would call the autodev-harness API
      await new Promise(resolve => setTimeout(resolve, 1000));
      console.log('Starting harness with brief:', brief);
    } finally {
      setLoading(false);
    }
  };
  
  return { start, loading };
}
