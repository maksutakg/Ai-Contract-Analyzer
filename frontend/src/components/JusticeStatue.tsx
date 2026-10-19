// Engraving-style Justitia on a plinth: blindfolded, scales raised, sword lowered. Shadowed planes
// are hatched rather than filled, the way a printed engraving models form.
export function JusticeStatue({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 200 360"
      role="img"
      aria-label="Statue of Justice: blindfolded, holding scales aloft in one hand and a sword in the other"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <defs>
        <pattern id="statue-hatch" width="2.6" height="2.6" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
          <line x1="0" y1="0" x2="0" y2="2.6" stroke="currentColor" strokeWidth="0.55" />
        </pattern>
      </defs>

      {/* Scales, held high so the pans clear the head */}
      <circle cx="61" cy="25" r="2.6" />
      <path d="M61 28v34" />
      <path d="M27 36q34-6 68 0" strokeWidth="2" />
      <path d="M27 36l-11 34M27 36v34M27 36l11 34M95 36l-11 34M95 36v34M95 36l11 34" strokeWidth="0.6" />
      <path d="M13 70q14 10 28 0z" fill="url(#statue-hatch)" />
      <path d="M13 70q14 10 28 0" />
      <path d="M81 70q14 10 28 0z" fill="url(#statue-hatch)" />
      <path d="M81 70q14 10 28 0" />

      {/* Raised arm, drawn with volume */}
      <path d="M85 134c-9-22-18-46-24-70M90 137c-9-23-18-47-24-71" />
      <circle cx="63" cy="63" r="3.6" fill="var(--paper)" />

      {/* Robe: body, shaded right side, fall of the himation, belt and folds */}
      <path d="M84 128c-5 42-12 102-20 164q36 9 72 0c-8-62-15-122-20-164z" fill="var(--paper)" />
      <path d="M104 134c7 40 12 98 22 158q6 1 10 0c-8-62-15-122-20-164z" fill="url(#statue-hatch)" stroke="none" />
      <path d="M85 132c13 18 24 32 32 50" />
      <path d="M86 168q14 6 28 0" strokeWidth="1" />
      <path d="M92 173c-3 38-10 80-18 118M100 175c0 40-2 80-4 118M108 173c2 40 7 80 14 119M80 228c-2 22-6 42-10 62" strokeWidth="0.7" />
      <path d="M66 286q34 10 68 0" strokeWidth="0.7" />

      {/* Head, hair and blindfold with trailing ends */}
      <path d="M100 116v12" />
      <ellipse cx="100" cy="103" rx="11" ry="13" fill="var(--paper)" />
      <circle cx="100" cy="87" r="5.5" fill="var(--paper)" />
      <path d="M89 98q11 3 22 0v5q-11 3-22 0z" fill="currentColor" />
      <path d="M111 100c5 2 8 6 9 12M111 102c3 4 4 9 3 14" strokeWidth="0.8" />

      {/* Lowered arm and sword, its tip resting on the plinth */}
      <path d="M112 136c6 22 11 46 14 68M117 133c7 24 12 48 15 70" />
      <circle cx="128" cy="189" r="2.8" />
      <path d="M128 192v12M118 206h20" />
      <path d="M125 210l3 82 3-82z" fill="var(--paper)" />
      <path d="M128 212v74" strokeWidth="0.5" />
      <circle cx="128" cy="207" r="4" fill="var(--paper)" />

      {/* Plinth, its right face hatched */}
      <path d="M60 296h80v8H60z" fill="var(--paper)" />
      <path d="M66 304h68v36H66z" fill="var(--paper)" />
      <path d="M118 304h16v36h-16z" fill="url(#statue-hatch)" />
      <path d="M54 340h92v10H54z" fill="var(--paper)" />
      <path d="M76 322h34" strokeWidth="0.6" />
    </svg>
  );
}
