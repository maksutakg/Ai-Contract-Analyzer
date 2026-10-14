import { useEffect, useState } from "react";

const SLOW_AFTER_SECONDS = 180;

const STEPS = [
  "Metni maddelere ayırıyor",
  "Her maddeyi risk açısından değerlendiriyor",
  "Riskler için Yargıtay, Danıştay ve KVKK kararlarını arıyor",
  "Bulunan kararların gerekçesini okuyup raporu hazırlıyor",
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
  const elapsed = seconds < 60 ? `${seconds} sn` : `${Math.floor(seconds / 60)} dk ${seconds % 60} sn`;

  return (
    <section className="waiting sheet" aria-live="polite" aria-busy="true">
      <p className="waiting-file">{fileName}</p>
      <h2 className="waiting-title">İnceleniyor</h2>
      <p className="waiting-clock" role="timer" aria-label={`Geçen süre ${elapsed}`}>
        {elapsed}
      </p>
      <p className="waiting-note">
        Genellikle 1–2 dakika sürer; emsal karar arama servisinin hız sınırı nedeniyle bekleme normaldir.
      </p>

      {/* What the backend does, in order. Deliberately not a progress bar: the API reports no stages. */}
      <ol className="waiting-steps">
        {STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      {seconds >= SLOW_AFTER_SECONDS && (
        <p className="alert" role="status">
          Analiz beklenenden uzun sürüyor. Bekleyebilir ya da iptal edip tekrar deneyebilirsiniz.
        </p>
      )}

      <button type="button" className="button-quiet" onClick={onCancel}>
        İptal et
      </button>
    </section>
  );
}
