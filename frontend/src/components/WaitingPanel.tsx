import { useEffect, useState } from "react";

const SLOW_AFTER_SECONDS = 180;

const STEPS = [
  "Splitting the text into clauses",
  "Assessing each clause for legal risk",
  "Searching court and authority decisions for each risk",
  "Reading the reasoning of the decisions found and writing the report",
];

interface Props {
  fileName: string;
  startedAt: number;
  onCancel: () => void;
}

export function WaitingPanel({ fileName, startedAt, onCancel }: Props) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const elapsed = seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;

  return (
    <section className="waiting sheet" aria-live="polite" aria-busy="true">
      <p className="waiting-file">{fileName}</p>
      <h2 className="waiting-title">Analyzing</h2>
      <p className="waiting-clock" role="timer" aria-label={`Elapsed ${elapsed}`}>
        {elapsed}
      </p>
      <p className="waiting-note">
        This usually takes one to two minutes; the case law service limits how fast it can be searched.
      </p>

      {/* What the backend does, in order. Deliberately not a progress bar: the API reports no stages. */}
      <ol className="waiting-steps">
        {STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      {seconds >= SLOW_AFTER_SECONDS && (
        <p className="alert" role="status">
          This is taking longer than usual. Keep waiting, or cancel and try again.
        </p>
      )}

      <button type="button" className="button-quiet" onClick={onCancel}>
        Cancel
      </button>
    </section>
  );
}
