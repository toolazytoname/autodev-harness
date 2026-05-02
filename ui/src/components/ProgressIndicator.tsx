import type { ExecutionProgress } from '../types';

interface Props {
  progress: ExecutionProgress;
}

export function ProgressIndicator({ progress }: Props) {
  const totalTests = progress.passedTests + progress.failedTests + progress.skippedTests;
  const percent = progress.totalTests > 0 ? (totalTests / progress.totalTests) * 100 : 0;

  const formatTime = (seconds: number | null): string => {
    if (seconds === null) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
        <span>
          {progress.isRunning ? (
            <span style={{ color: 'var(--color-accent)' }}>Running...</span>
          ) : progress.isCancelled ? (
            <span style={{ color: 'var(--color-warning)' }}>Cancelled</span>
          ) : progress.passedTests + progress.failedTests > 0 ? (
            <span style={{ color: progress.failedTests > 0 ? 'var(--color-error)' : 'var(--color-success)' }}>
              {progress.failedTests > 0 ? 'Failed' : 'Complete'}
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>Ready</span>
          )}
          {progress.currentTest && (
            <span style={{ color: 'var(--text-muted)', marginLeft: '0.5rem' }}>
              {progress.currentSuite}: {progress.currentTest}
            </span>
          )}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          {formatTime(progress.elapsed)} / ETA: {formatTime(progress.eta)}
        </span>
      </div>

      <div style={{ height: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${percent}%`,
            background: progress.failedTests > 0
              ? 'linear-gradient(90deg, var(--color-success) 0%, var(--color-success) ' + ((progress.passedTests / totalTests) * 100) + '%, var(--color-error) ' + ((progress.passedTests / totalTests) * 100) + '%, var(--color-error) 100%)'
              : 'var(--color-success)',
            transition: 'width 0.3s ease',
          }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem', fontSize: '0.75rem' }}>
        <span style={{ color: 'var(--color-success)' }}>
          {progress.passedTests > 0 && `passed ${progress.passedTests}`}
        </span>
        <span style={{ color: 'var(--color-error)' }}>
          {progress.failedTests > 0 && `failed ${progress.failedTests}`}
        </span>
        <span style={{ color: 'var(--color-warning)' }}>
          {progress.skippedTests > 0 && `skipped ${progress.skippedTests}`}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          {progress.completedSuites}/{progress.totalSuites} suites
        </span>
      </div>
    </div>
  );
}
