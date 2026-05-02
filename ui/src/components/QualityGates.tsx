import { CheckCircle, XCircle, Circle } from 'lucide-react';
import type { GateStatus } from '../types';

interface Props {
  gateStatus: GateStatus;
}

const GATE_LABELS: Record<string, string> = {
  lint: 'Lint',
  build: 'Build',
  test: 'Tests',
  e2e: 'E2E',
  security: 'Security',
};

export function QualityGates({ gateStatus }: Props) {
  const gates = ['lint', 'build', 'test', 'e2e', 'security'];

  return (
    <div className="card">
      <h2>Quality Gates</h2>
      <div className="gates">
        {gates.map(gate => {
          const status = gateStatus[gate] || 'pending';
          return (
            <div key={gate} className={`gate ${status}`}>
              {status === 'pass' && <CheckCircle size={16} />}
              {status === 'fail' && <XCircle size={16} />}
              {status === 'pending' && <Circle size={16} />}
              <span>{GATE_LABELS[gate] || gate}</span>
            </div>
          );
        })}
      </div>
      <div className="timestamp">
        Updated: {new Date().toLocaleTimeString()}
      </div>
    </div>
  );
}
