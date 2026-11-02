import { useEffect, useRef, useState } from "react";

import {
  AuthenticationError,
  analyzeContract,
  clearStoredToken,
  fetchCurrentUser,
  getStoredToken,
} from "./api";
import { AuthPanel } from "./components/AuthPanel";
import { Report } from "./components/Report";
import { SourcePlate } from "./components/SourcePlate";
import { UploadPanel } from "./components/UploadPanel";
import { WaitingPanel } from "./components/WaitingPanel";
import type { AuthSession, AuthUser, ContractReport, ContractType } from "./types";

type State =
  | { kind: "idle"; error?: string }
  | { kind: "analyzing"; fileName: string; startedAt: number }
  | { kind: "done"; fileName: string; report: ContractReport };

export function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecking, setAuthChecking] = useState<boolean>(() => Boolean(getStoredToken()));
  const [authError, setAuthError] = useState<string | undefined>(undefined);
  const [state, setState] = useState<State>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!getStoredToken()) {
      setAuthChecking(false);
      return;
    }
    let active = true;
    fetchCurrentUser()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function handleAuthenticated(session: AuthSession) {
    setAuthError(undefined);
    setUser(session.user);
  }

  function handleSignOut() {
    controller.current?.abort();
    clearStoredToken();
    setUser(null);
    setState({ kind: "idle" });
  }

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
      if (error instanceof AuthenticationError) {
        setUser(null);
        setAuthError(error.message);
        setState({ kind: "idle" });
        return;
      }
      setState({ kind: "idle", error: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <div className="app-container">
      <header className="top-nav">
        <div className="top-nav-inner">
          <div className="top-nav-brand">
            <svg
              className="top-nav-mark"
              viewBox="0 0 40 40"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 6v28M12 34h16M6 12h28M6 12l-4 12M6 12l4 12M34 12l-4 12M34 12l4 12" />
              <path d="M1 24q5 5 10 0zM29 24q5 5 10 0z" fill="currentColor" />
              <circle cx="20" cy="5" r="2" />
            </svg>
            <span className="top-nav-title">Contract Risk Review</span>
          </div>

          <div className="top-nav-actions">
            {user && state.kind === "done" && (
              <button
                type="button"
                className="nav-pill-button"
                onClick={() => setState({ kind: "idle" })}
              >
                Analyze another contract ↗
              </button>
            )}
            {user && (
              <>
                <span className="top-nav-user" title={user.email}>
                  {user.email}
                </span>
                <button type="button" className="button-quiet" onClick={handleSignOut}>
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <div className="app">
        <main>
          {authChecking ? (
            <p className="muted">Checking session...</p>
          ) : !user ? (
            <div className="landing">
              <AuthPanel initialError={authError} onAuthenticated={handleAuthenticated} />
              <SourcePlate />
            </div>
          ) : (
            <>
              {state.kind === "idle" && (
                <div className="landing">
                  <UploadPanel error={state.error} onSubmit={start} />
                  <SourcePlate />
                </div>
              )}
              {state.kind === "analyzing" && (
                <WaitingPanel
                  fileName={state.fileName}
                  startedAt={state.startedAt}
                  onCancel={() => controller.current?.abort()}
                />
              )}
              {state.kind === "done" && <Report fileName={state.fileName} report={state.report} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
