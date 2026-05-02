import type { TaskQueue } from '../types';

interface Props {
  taskQueue: TaskQueue;
}

export function TaskProgress({ taskQueue }: Props) {
  const { tasks, progress } = taskQueue;
  const total = tasks.length;
  const completed = progress.completed;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="card">
      <h2>Task Progress</h2>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="metric">{completed}/{total}</div>
      <p style={{ color: 'var(--text-muted)', marginTop: '0.5rem' }}>{pct}% complete</p>
      
      <ul className="task-list">
        {tasks
          .sort((a, b) => a.priority - b.priority)
          .slice(0, 5)
          .map(task => (
            <li key={task.id}>
              <span className={`task-dot ${task.status}`} />
              <span className="task-id">{task.id}</span>
              <span>{task.name}</span>
            </li>
          ))}
      </ul>
      
      <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem', fontSize: '0.875rem' }}>
        <span style={{ color: 'var(--green)' }}>✓ {progress.completed} done</span>
        <span style={{ color: 'var(--yellow)' }}>⟳ {progress.inProgress} active</span>
        <span style={{ color: 'var(--text-muted)' }}>○ {progress.pending} pending</span>
        {progress.failed > 0 && (
          <span style={{ color: 'var(--red)' }}>✗ {progress.failed} failed</span>
        )}
      </div>
    </div>
  );
}
