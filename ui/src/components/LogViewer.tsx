import { useState, useEffect } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface LogEntry {
  timestamp: string;
  level: 'info' | 'warn' | 'error';
  message: string;
}

const SAMPLE_LOGS: LogEntry[] = [
  { timestamp: '10:23:45', level: 'info', message: '[PLANNER] Generating product specification...' },
  { timestamp: '10:23:52', level: 'info', message: '[PLANNER] Created SPEC.md with 14 features' },
  { timestamp: '10:23:55', level: 'info', message: '[PLANNER] Task queue generated: 8 tasks' },
  { timestamp: '10:24:01', level: 'info', message: '[GENERATOR] Starting task-001: Project setup' },
  { timestamp: '10:24:15', level: 'info', message: '[GATES] lint ✓, build ✓' },
  { timestamp: '10:24:18', level: 'info', message: '[TASK] task-001 completed' },
  { timestamp: '10:24:22', level: 'info', message: '[GENERATOR] Starting task-002: Authentication' },
  { timestamp: '10:24:35', level: 'warn', message: '[GATES] test: 2 failures (auth module)' },
  { timestamp: '10:24:40', level: 'info', message: '[GAN] Running evaluation...' },
  { timestamp: '10:24:55', level: 'info', message: '[GAN] Score: 5.1/10 - Needs improvement' },
];

export function LogViewer() {
  const [expanded, setExpanded] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>(SAMPLE_LOGS);

  useEffect(() => {
    const interval = setInterval(() => {
      if (Math.random() > 0.7) {
        const newLog: LogEntry = {
          timestamp: new Date().toLocaleTimeString('en-US', { hour12: false }),
          level: Math.random() > 0.9 ? 'warn' : 'info',
          message: `[${Math.random() > 0.5 ? 'GAN' : 'GENERATOR'}] Processing...`,
        };
        setLogs(prev => [...prev.slice(-20), newLog]);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const displayLogs = expanded ? logs : logs.slice(-5);

  return (
    <div className="card">
      <div
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setExpanded(!expanded)}
      >
        <h2>Live Logs</h2>
        {expanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
      </div>
      <div className="logs" style={{ marginTop: '1rem' }}>
        {displayLogs.map((log, i) => (
          <div key={i} style={{ marginBottom: '0.25rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>[{log.timestamp}]</span>{' '}
            <span style={{
              color: log.level === 'error' ? 'var(--red)' : log.level === 'warn' ? 'var(--yellow)' : 'var(--text)'
            }}>
              {log.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
