import { useState, useCallback, useRef, useEffect } from 'react';
import type { TestSuite, TestResult, RunConfig, ExecutionProgress, TestStatus } from '../types';

interface UseTestExecutionReturn {
  progress: ExecutionProgress;
  suites: TestSuite[];
  isRunning: boolean;
  error: string | null;
  startExecution: (config: RunConfig) => void;
  cancelExecution: () => void;
  retryFailed: () => void;
  clearResults: () => void;
}

const initialProgress: ExecutionProgress = {
  totalSuites: 0,
  completedSuites: 0,
  totalTests: 0,
  passedTests: 0,
  failedTests: 0,
  skippedTests: 0,
  currentSuite: null,
  currentTest: null,
  startTime: '',
  eta: null,
  elapsed: 0,
  isRunning: false,
  isCancelled: false,
};

export function useTestExecution(): UseTestExecutionReturn {
  const [progress, setProgress] = useState<ExecutionProgress>(initialProgress);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const elapsedTimerRef = useRef<number | null>(null);

  const clearResults = useCallback(() => {
    setSuites([]);
    setProgress(initialProgress);
    setError(null);
  }, []);

  const cancelExecution = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }

    setProgress(prev => ({
      ...prev,
      isRunning: false,
      isCancelled: true,
    }));
    setIsRunning(false);
  }, []);

  const calculateEta = (elapsed: number, completed: number, total: number): number | null => {
    if (completed === 0 || total === 0) return null;
    const avgTimePerTest = elapsed / completed;
    const remaining = total - completed;
    return Math.round(remaining * avgTimePerTest);
  };

  const startExecution = useCallback((config: RunConfig) => {
    cancelExecution();
    clearResults();

    setIsRunning(true);
    setError(null);

    const startTimeIso = new Date().toISOString();

    setProgress(prev => ({
      ...prev,
      startTime: startTimeIso,
      isRunning: true,
      isCancelled: false,
      totalSuites: config.suites.length,
    }));

    simulateExecution(config, setProgress, setSuites, setIsRunning);
  }, [cancelExecution, clearResults]);

  const retryFailed = useCallback(() => {
    const failedSuites = suites.filter(s => s.failed > 0);
    if (failedSuites.length === 0) return;

    const config: RunConfig = {
      suites: failedSuites.map(s => s.id),
      parallel: true,
      maxWorkers: 2,
      retryFailed: true,
      maxRetries: 1,
      timeout: 60000,
      verbose: true,
    };

    startExecution(config);
  }, [suites, startExecution]);

  useEffect(() => {
    if (isRunning && progress.startTime) {
      elapsedTimerRef.current = window.setInterval(() => {
        setProgress(prev => {
          const start = new Date(prev.startTime).getTime();
          const now = Date.now();
          const elapsed = Math.round((now - start) / 1000);
          const eta = calculateEta(
            elapsed,
            prev.passedTests + prev.failedTests + prev.skippedTests,
            prev.totalTests
          );
          return { ...prev, elapsed, eta };
        });
      }, 1000);
    }

    return () => {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
      }
    };
  }, [isRunning, progress.startTime]);

  return {
    progress,
    suites,
    isRunning,
    error,
    startExecution,
    cancelExecution,
    retryFailed,
    clearResults,
  };
}

function simulateExecution(
  config: RunConfig,
  setProgress: (updater: (prev: ExecutionProgress) => ExecutionProgress) => void,
  setSuites: React.Dispatch<React.SetStateAction<TestSuite[]>>,
  setIsRunning: (running: boolean) => void
) {
  const demoSuites: TestSuite[] = config.suites.map((suiteId, idx) => ({
    id: suiteId,
    name: `Test Suite ${idx + 1}`,
    tests: [],
    status: 'pending' as TestStatus,
    startTime: null,
    endTime: null,
    totalTests: Math.floor(Math.random() * 5) + 3,
    passed: 0,
    failed: 0,
    skipped: 0,
    duration: 0,
  }));

  let suiteIndex = 0;
  let testIndex = 0;
  let currentSuite: TestSuite | null = null;

  const executionInterval = setInterval(() => {
    if (config.suites.length === 0) {
      clearInterval(executionInterval);
      setIsRunning(false);
      return;
    }

    if (testIndex === 0 && suiteIndex < demoSuites.length) {
      currentSuite = {
        ...demoSuites[suiteIndex],
        status: 'running',
        startTime: new Date().toISOString(),
        tests: demoSuites[suiteIndex].tests,
      };
      setSuites(prev => prev.map(s => s.id === currentSuite!.id ? currentSuite! : s));

      setProgress(prev => ({
        ...prev,
        currentSuite: currentSuite!.id,
        totalTests: demoSuites.reduce((acc, s) => acc + s.totalTests, 0),
      }));
    }

    if (currentSuite && testIndex < currentSuite.totalTests) {
      const testResult: TestResult = {
        id: `${currentSuite.id}-test-${testIndex}`,
        name: `Test case ${testIndex + 1}`,
        status: 'running',
        duration: 0,
        logs: [],
      };

      setTimeout(() => {
        const rand = Math.random();
        const status: TestStatus = rand > 0.9 ? 'failed' : rand > 0.95 ? 'skipped' : 'passed';
        const completedTest: TestResult = {
          ...testResult,
          status,
          duration: Math.floor(Math.random() * 500) + 50,
          error: status === 'failed' ? 'Assertion failed: expected 200 but got 404' : undefined,
          logs: [
            { timestamp: new Date().toISOString(), level: 'info', message: `Running ${testResult.name}...` },
            { timestamp: new Date().toISOString(), level: 'info', message: status === 'passed' ? 'Test passed' : (status === 'failed' ? 'Test failed' : 'Test skipped') },
          ],
        };

        setSuites(prev => prev.map(s => {
          if (s.id === currentSuite!.id) {
            const updatedTests = [...s.tests, completedTest];
            return {
              ...s,
              tests: updatedTests,
              passed: updatedTests.filter(t => t.status === 'passed').length,
              failed: updatedTests.filter(t => t.status === 'failed').length,
              skipped: updatedTests.filter(t => t.status === 'skipped').length,
            };
          }
          return s;
        }));

        setProgress(prev => ({
          ...prev,
          currentTest: completedTest.name,
          passedTests: status === 'passed' ? prev.passedTests + 1 : prev.passedTests,
          failedTests: status === 'failed' ? prev.failedTests + 1 : prev.failedTests,
          skippedTests: status === 'skipped' ? prev.skippedTests + 1 : prev.skippedTests,
        }));
      }, 100);

      testIndex++;
    } else if (currentSuite) {
      const completedSuite: TestSuite = {
        ...currentSuite,
        status: currentSuite.failed > 0 ? 'failed' : 'passed',
        endTime: new Date().toISOString(),
        duration: new Date().getTime() - new Date(currentSuite.startTime!).getTime(),
      };
      setSuites(prev => prev.map(s => s.id === completedSuite.id ? completedSuite : s));

      setProgress(prev => ({
        ...prev,
        completedSuites: prev.completedSuites + 1,
        currentSuite: null,
        currentTest: null,
      }));

      testIndex = 0;
      suiteIndex++;
      currentSuite = null;
    }

    if (suiteIndex >= demoSuites.length) {
      clearInterval(executionInterval);
      setProgress(prev => ({
        ...prev,
        isRunning: false,
        eta: 0,
      }));
      setIsRunning(false);
    }
  }, 500);
}
