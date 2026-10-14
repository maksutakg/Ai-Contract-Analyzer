import { useRef, useState } from "react";

import { analyzeContract } from "./api";
import { Report } from "./components/Report";
import { UploadPanel } from "./components/UploadPanel";
import { WaitingPanel } from "./components/WaitingPanel";
import type { ContractReport, ContractType } from "./types";

type State =
  | { kind: "idle"; error?: string }
  | { kind: "analyzing"; fileName: string; startedAt: number }
  | { kind: "done"; fileName: string; report: ContractReport };

export function App() {
  const [state, setState] = useState<State>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);

  async function start(file: File, contractType: ContractType | "") {
    controller.current = new AbortController();
    setState({ kind: "analyzing", fileName: file.name, startedAt: Date.now() });
    try {
      const report = await analyzeContract(file, contractType, controller.current.signal);
      setState({ kind: "done", fileName: file.name, report });
    } catch (error) {
      if (controller.current.signal.aborted) {
        setState({ kind: "idle" });
        return;
      }
      setState({ kind: "idle", error: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <div className="app">
      <header className="masthead">
        <h1>Sözleşme risk analizi</h1>
        {state.kind === "done" && (
          <button type="button" className="button-quiet" onClick={() => setState({ kind: "idle" })}>
            Yeni sözleşme incele
          </button>
        )}
      </header>
      <main>
        {state.kind === "idle" && <UploadPanel error={state.error} onSubmit={start} />}
        {state.kind === "analyzing" && (
          <WaitingPanel
            fileName={state.fileName}
            startedAt={state.startedAt}
            onCancel={() => controller.current?.abort()}
          />
        )}
        {state.kind === "done" && <Report fileName={state.fileName} report={state.report} />}
      </main>
    </div>
  );
}
