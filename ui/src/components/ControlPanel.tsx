import { Play, Pause, RotateCcw, Settings } from 'lucide-react';
import { useState } from 'react';

interface Props {
  running: boolean;
  onStart: (brief: string) => void;
  onStop: () => void;
  onRestart: () => void;
}

export function ControlPanel({ running, onStart, onStop, onRestart }: Props) {
  const [brief, setBrief] = useState('');

  const handleStart = () => {
    if (brief.trim()) {
      onStart(brief.trim());
      setBrief('');
    }
  };

  return (
    <div className="card">
      <h2>Control Panel</h2>
      
      <div className="controls" style={{ marginBottom: '1.5rem' }}>
        {running ? (
          <button className="btn btn-danger" onClick={onStop}>
            <Pause size={16} />
            Stop
          </button>
        ) : (
          <button className="btn btn-primary" onClick={handleStart} disabled={!brief.trim()}>
            <Play size={16} />
            Start
          </button>
        )}
        <button className="btn btn-secondary" onClick={onRestart}>
          <RotateCcw size={16} />
          Restart
        </button>
        <button className="btn btn-secondary">
          <Settings size={16} />
          Settings
        </button>
      </div>
      
      <div>
        <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          Project Brief
        </label>
        <textarea
          value={brief}
          onChange={e => setBrief(e.target.value)}
          placeholder="Describe what to build... e.g., 'Build a task management app with Kanban boards'"
          disabled={running}
          style={{
            width: '100%',
            minHeight: '80px',
            padding: '0.75rem',
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            color: 'var(--text)',
            fontSize: '0.875rem',
            resize: 'vertical',
          }}
        />
      </div>
    </div>
  );
}
