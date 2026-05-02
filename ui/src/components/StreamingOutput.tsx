import { useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Minus, Clock } from 'lucide-react';
import type { TestSuite, TestResult } from '../types';

interface Props {
  suites: TestSuite[];
}

const ANSI_COLORS: Record<string, string> = {
  '30': '#000000', '31': '#ef4444', '32': '#22c55e', '33': '#eab308',
  '34': '#3b82f6', '35': '#a855f7', '36': '#06b6d4', '37': '#ffffff',
  '90': '#6b7280', '91': '#f87171', '92': '#4ade80', '93': '#facc15',
  '94': '#60a5fa', '95': '#c084fc', '96': '#22d3ee', '97': '#f9fafb',
};

export function StreamingOutput({ suites }: Props) {
  const [expandedSuites, setExpandedSuites] = useState<Set<string>>(new Set());
  const [expandedTests, setExpandedTests] = useState<Set<string>>(new Set());
  const outputRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [suites]);

  const toggleSuite = (suiteId: string) => {
    setExpandedSuites(prev => {
      const next = new Set(prev);
      next.has(suiteId) ? next.delete(suiteId) : next.add(suiteId);
      return next;
    });
  };

  const toggleTest = (testId: string) => {
    setExpandedTests(prev => {
      const next = new Set(prev);
      next.has(testId) ? next.delete(testId) : next.add(testId);
      return next;
    });
  };

  const parseAnsiToSpans = (text: string): React.ReactNode[] => {
    const parts: React.ReactNode[] = [];
    const regex = /\x1b\[([0-9;]*)m/g;
    let lastIndex = 0;
    let currentColor = 'inherit';
    let isBold = false;

    let match;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        const textContent = text.slice(lastIndex, match.index);
        parts.push(<span key={parts.length} style={{ color: currentColor, fontWeight: isBold ? 'bold' : undefined }}>{textContent}</span>);
      }

      const codes = match[1].split(';').map(Number);
      if (codes[0] === 0) {
        currentColor = 'inherit';
        isBold = false;
      } else {
        codes.forEach(code => {
          if (ANSI_COLORS[code.toString()]) currentColor = ANSI_COLORS[code.toString()];
          if (code === 1) isBold = true;
          if (code === 22) isBold = false;
        });
      }
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < text.length) {
      parts.push(<span key={parts.length}>{text.slice(lastIndex)}</span>);
    }

    return parts.length > 0 ? parts : [text];
  };

  const getStatusIcon = (status: TestResult['status']) => {
    switch (status) {
      case 'passed': return <CheckCircle size={14} style={{ color: 'var(--color-success)' }} />;
      case 'failed': return <XCircle size={14} style={{ color: 'var(--color-error)' }} />;
      case 'skipped': return <Minus size={14} style={{ color: 'var(--color-warning)' }} />;
      case 'running': return <Clock size={14} style={{ color: 'var(--color-accent)' }} />;
      default: return null;
    }
  };

  const formatDuration = (ms: number) => ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;

  if (suites.length === 0) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-tertiary)', borderRadius: '8px' }}>
        No test results yet. Configure and run tests to see output.
      </div>
    );
  }

  return (
    <div ref={outputRef} style={{ maxHeight: '400px', overflow: 'auto', background: '#1a1a2e', borderRadius: '8px', padding: '1rem', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.8125rem', color: '#e2e8f0' }}>
      {suites.map(suite => (
        <div key={suite.id} style={{ marginBottom: '1rem' }}>
          <div onClick={() => toggleSuite(suite.id)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', padding: '0.5rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px', marginBottom: expandedSuites.has(suite.id) ? '0.5rem' : 0 }}>
            {expandedSuites.has(suite.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span style={{ fontWeight: 'bold' }}>{suite.name}</span>
            <span style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>
              {suite.passed}/{suite.totalTests} passed
              {suite.failed > 0 && <span style={{ color: 'var(--color-error)' }}>, {suite.failed} failed</span>}
            </span>
          </div>

          {expandedSuites.has(suite.id) && (
            <div style={{ marginLeft: '1.5rem' }}>
              {suite.tests.map(test => (
                <div key={test.id} style={{ marginBottom: '0.5rem' }}>
                  <div onClick={() => toggleTest(test.id)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', padding: '0.25rem 0.5rem' }}>
                    {getStatusIcon(test.status)}
                    <span>{test.name}</span>
                    <span style={{ color: 'var(--text-muted)', marginLeft: 'auto', fontSize: '0.75rem' }}>{formatDuration(test.duration)}</span>
                  </div>

                  {expandedTests.has(test.id) && (
                    <div style={{ marginLeft: '1.5rem', padding: '0.5rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                      {test.logs.map((log, i) => (
                        <div key={i} style={{ marginBottom: '0.25rem' }}>
                          <span style={{ color: 'var(--text-muted)', marginRight: '0.5rem' }}>[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                          <span style={{ color: log.level === 'error' ? '#ef4444' : log.level === 'warn' ? '#eab308' : log.level === 'debug' ? '#6b7280' : 'inherit' }}>
                            {parseAnsiToSpans(log.message)}
                          </span>
                        </div>
                      ))}
                      {test.error && <div style={{ marginTop: '0.5rem', color: '#ef4444' }}><strong>Error:</strong> {test.error}</div>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
