import type { GanSummary } from '../types';

interface Props {
  ganSummary: GanSummary | null;
}

export function GanScore({ ganSummary }: Props) {
  if (!ganSummary) {
    return (
      <div className="card">
        <h2>GAN Quality Score</h2>
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
          No evaluation data
        </div>
      </div>
    );
  }

  const { finalScore, passed, iterations, scores, elapsed } = ganSummary;
  const scoreClass = passed ? 'pass' : 'fail';

  return (
    <div className="card">
      <h2>GAN Quality Score</h2>
      
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '1rem' }}>
        <div className={`score-ring ${scoreClass}`}>
          <span className="value">{finalScore.toFixed(1)}</span>
          <span className="label">/ 10</span>
        </div>
      </div>
      
      <div style={{ textAlign: 'center', marginTop: '1rem' }}>
        {passed ? (
          <span style={{ color: 'var(--green)', fontWeight: 600 }}>✓ PASSED</span>
        ) : (
          <span style={{ color: 'var(--yellow)', fontWeight: 600 }}>⟳ IN PROGRESS</span>
        )}
      </div>
      
      <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: '1.5rem', fontSize: '0.875rem' }}>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Iterations</div>
          <div style={{ fontWeight: 600 }}>{iterations}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Elapsed</div>
          <div style={{ fontWeight: 600 }}>{elapsed}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Threshold</div>
          <div style={{ fontWeight: 600 }}>7.0</div>
        </div>
      </div>
      
      {scores.length > 0 && (
        <div style={{ marginTop: '1.5rem' }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: '0.5rem', fontSize: '0.75rem' }}>
            Score Trend
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'end' }}>
            {scores.map((score, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                <div
                  style={{
                    height: `${score * 10}px`,
                    background: score >= 7 ? 'var(--green)' : 'var(--yellow)',
                    borderRadius: '4px 4px 0 0',
                  }}
                />
                <div style={{ fontSize: '0.625rem', marginTop: '0.25rem' }}>{score}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
