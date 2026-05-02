import { useState } from 'react';
import { Play, Square, RotateCcw, Settings } from 'lucide-react';
import type { RunConfig } from '../types';
import { StreamingOutput } from './StreamingOutput';
import { ProgressIndicator } from './ProgressIndicator';
import { useTestExecution } from '../hooks/useTestExecution';

const AVAILABLE_SUITES = [
  { id: 'auth', name: 'Authentication Tests' },
  { id: 'api', name: 'API Tests' },
  { id: 'ui', name: 'UI Component Tests' },
  { id: 'integration', name: 'Integration Tests' },
  { id: 'e2e', name: 'End-to-End Tests' },
];

export function TestExecutionPanel() {
  const { progress, suites, isRunning, error, startExecution, cancelExecution, retryFailed, clearResults } = useTestExecution();
  const [showConfig, setShowConfig] = useState(false);
  const [selectedSuites, setSelectedSuites] = useState<string[]>(['auth', 'api']);
  const [config, setConfig] = useState<RunConfig>({
    suites: selectedSuites,
    parallel: true,
    maxWorkers: 4,
    retryFailed: true,
    maxRetries: 3,
    timeout: 60000,
    verbose: true,
  });

  const toggleSuite = (suiteId: string) => {
    setSelectedSuites(prev =>
      prev.includes(suiteId)
        ? prev.filter(id => id !== suiteId)
        : [...prev, suiteId]
    );
  };

  const handleStart = () => {
    startExecution({ ...config, suites: selectedSuites });
  };

  const hasFailedTests = suites.some(s => s.failed > 0);

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2>Test Execution</h2>
        <button
          className="btn btn-secondary"
          onClick={() => setShowConfig(!showConfig)}
          style={{ padding: '0.5rem' }}
        >
          <Settings size={16} />
        </button>
      </div>

      {showConfig && !isRunning && (
        <div style={{ marginBottom: '1rem', padding: '1rem', background: 'var(--bg-tertiary)', borderRadius: '8px' }}>
          <h4 style={{ marginBottom: '0.75rem' }}>Select Test Suites</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
            {AVAILABLE_SUITES.map(suite => (
              <label key={suite.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selectedSuites.includes(suite.id)}
                  onChange={() => toggleSuite(suite.id)}
                />
                {suite.name}
              </label>
            ))}
          </div>

          <h4 style={{ marginBottom: '0.75rem' }}>Configuration</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={config.parallel}
                onChange={e => setConfig(prev => ({ ...prev, parallel: e.target.checked }))}
              />
              Parallel Execution
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={config.retryFailed}
                onChange={e => setConfig(prev => ({ ...prev, retryFailed: e.target.checked }))}
              />
              Auto Retry Failed
            </label>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem' }}>Max Workers</label>
              <input
                type="number"
                min={1}
                max={16}
                value={config.maxWorkers}
                onChange={e => setConfig(prev => ({ ...prev, maxWorkers: parseInt(e.target.value) || 1 }))}
                style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem' }}>Timeout (ms)</label>
              <input
                type="number"
                min={1000}
                step={1000}
                value={config.timeout}
                onChange={e => setConfig(prev => ({ ...prev, timeout: parseInt(e.target.value) || 60000 }))}
                style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}
              />
            </div>
          </div>
        </div>
      )}

      <ProgressIndicator progress={progress} />

      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', marginBottom: '1rem' }}>
        {isRunning ? (
          <button className="btn btn-danger" onClick={cancelExecution}>
            <Square size={16} />
            Cancel
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={handleStart}
            disabled={selectedSuites.length === 0}
          >
            <Play size={16} />
            Run Tests
          </button>
        )}

        {hasFailedTests && !isRunning && (
          <button className="btn btn-secondary" onClick={retryFailed}>
            <RotateCcw size={16} />
            Retry Failed
          </button>
        )}

        {!isRunning && suites.length > 0 && (
          <button className="btn btn-secondary" onClick={clearResults}>
            Clear Results
          </button>
        )}
      </div>

      {error && (
        <div style={{
          padding: '0.75rem',
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid var(--color-error)',
          borderRadius: '8px',
          color: 'var(--color-error)',
          marginBottom: '1rem',
        }}>
          {error}
        </div>
      )}

      <StreamingOutput suites={suites} />
    </div>
  );
}
