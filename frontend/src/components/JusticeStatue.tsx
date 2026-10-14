// Line drawing of Themis: blindfold, raised scales, lowered sword, on a plinth.
export function JusticeStatue({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 200 300"
      role="img"
      aria-label="Gözleri bağlı, elinde terazi ve kılıç tutan adalet heykeli"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* Scales */}
      <path d="M42 28v14" />
      <circle cx="42" cy="25" r="3" />
      <path d="M14 42h56" />
      <path d="M14 42l-11 32M14 42l11 32M70 42l-11 32M70 42l11 32" strokeWidth="1.25" />
      <path d="M1 74q13 11 26 0z" fill="var(--sheet)" />
      <path d="M57 74q13 11 26 0z" fill="var(--sheet)" />

      {/* Raised arm holding the scales */}
      <path d="M88 126c-14-10-28-24-36-42-6-12-9-26-10-40" />

      {/* Head with blindfold and hair knot */}
      <circle cx="100" cy="100" r="13" fill="var(--sheet)" />
      <circle cx="100" cy="85" r="5" fill="var(--sheet)" />
      <path d="M87 98h26v6H87z" fill="var(--stamp)" stroke="var(--stamp)" />
      <path d="M113 101l7 4" stroke="var(--stamp)" />
      <path d="M100 113v9" />

      {/* Robe */}
      <path d="M86 124h28l26 142H60z" fill="var(--sheet)" />
      <path d="M95 132l-12 132M100 140l-4 124M106 134l8 130M90 150l-20 112" strokeWidth="1" />
      <path d="M84 150q16 8 34 0" strokeWidth="1.25" />

      {/* Lowered arm and sword */}
      <path d="M114 128c8 16 14 36 18 58" />
      <path d="M124 190h18M133 178v12" />
      <path d="M133 190l-4 7 4 68 4-68z" fill="var(--sheet)" />

      {/* Plinth */}
      <path d="M56 266h88v12H56zM44 278h112v14H44z" fill="var(--sheet)" />
    </svg>
  );
}
