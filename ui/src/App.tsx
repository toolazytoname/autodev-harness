import { TaskProgress } from './components/TaskProgress';
import { GanScore } from './components/GanScore';
import { QualityGates } from './components/QualityGates';
import { ControlPanel } from './components/ControlPanel';
import { LogViewer } from './components/LogViewer';
import { TestExecutionPanel } from './components/TestExecutionPanel';
import { useHarnessData, useStartHarness } from './hooks/useHarnessData';

function App() {
  const { taskQueue, ganSummary, gateStatus, running } = useHarnessData();
  const { start } = useStartHarness();

  return (
    <div className="app">
      <header className="header">
        <h1>🤖 AutoDevHarness</h1>
        <div className="live">
          <span className="live-dot" />
          <span>{running ? 'Running' : 'Idle'}</span>
        </div>
      </header>

      <div className="grid">
        {taskQueue && <TaskProgress taskQueue={taskQueue} />}
        <GanScore ganSummary={ganSummary} />
        <QualityGates gateStatus={gateStatus} />
        <ControlPanel
          running={running}
          onStart={start}
          onStop={() => console.log('Stop')}
          onRestart={() => console.log('Restart')}
        />
        <TestExecutionPanel />
      </div>

      <LogViewer />

      <div className="timestamp">
        Last updated: {new Date().toLocaleString()}
      </div>
    </div>
  );
}

export default App;
