import { useState, type FormEvent } from "react";

import { loginUser, registerUser } from "../api";
import type { AuthSession } from "../types";

interface Props {
  initialError?: string;
  onAuthenticated: (session: AuthSession) => void;
}

export function AuthPanel({ initialError, onAuthenticated }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [submitting, setSubmitting] = useState(false);

  function switchMode(nextMode: "login" | "register") {
    setMode(nextMode);
    setError(null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session =
        mode === "login"
          ? await loginUser(email, password)
          : await registerUser(email, password);
      onAuthenticated(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="upload auth-panel" aria-labelledby="auth-heading">
      <h2 id="auth-heading" className="upload-title">
        {mode === "login"
          ? "Sign in to review contracts against live case law"
          : "Create an account to start reviewing contracts"}
      </h2>
      <p className="lede">
        Every clause is checked for legal risk. Sign in with your email and password to upload PDF
        or DOCX agreements and inspect matching court decisions.
      </p>

      <div className="sheet auth-card">
        <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            aria-selected={mode === "login"}
            className={`auth-tab${mode === "login" ? " is-active" : ""}`}
            onClick={() => switchMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            aria-selected={mode === "register"}
            className={`auth-tab${mode === "register" ? " is-active" : ""}`}
            onClick={() => switchMode("register")}
          >
            Create account
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-field">
            <span className="auth-label">Email address</span>
            <input
              type="email"
              className="auth-input"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@company.com"
              autoComplete="email"
              required
            />
          </label>

          <label className="auth-field">
            <span className="auth-label">Password</span>
            <input
              type="password"
              className="auth-input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="At least 8 characters"
              minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
            />
          </label>

          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            className="button-primary auth-submit"
            disabled={submitting || !email.trim() || password.length < 8}
          >
            {submitting
              ? "Please wait..."
              : mode === "login"
                ? "Sign in to continue"
                : "Create account & continue"}
          </button>
        </form>
      </div>
    </section>
  );
}
