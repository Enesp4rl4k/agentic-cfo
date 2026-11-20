import styles from "./brand.module.css";

/**
 * Mythological figures, black-figure technique: a one-colour silhouette
 * (`currentColor`), details incised in the ground colour (`--inc`), one ember
 * detail each. Decorative only (`aria-hidden`), always faint and in the
 * background. Their motion is CSS and stops under `prefers-reduced-motion`.
 */

type FigureProps = { className?: string; width?: number; height?: number };

export function Hermes({ className, width = 92, height = 184 }: FigureProps) {
  return (
    <svg viewBox="0 0 200 400" width={width} height={height} className={className} aria-hidden="true" focusable="false" style={{ overflow: "visible" }}>
      <g className={styles.cloak} style={{ transformOrigin: "88px 124px" }}>
        <path d="M86 122 C62 140 50 190 44 242 L60 238 L66 252 L78 234 C80 192 86 156 96 132 Z" fill="currentColor" />
        <path d="M70 150 L58 232 M80 148 L70 236" fill="none" stroke="var(--inc)" strokeWidth="1.1" />
      </g>
      <g fill="currentColor">
        <rect x="40" y="372" width="120" height="12" rx="1" /><rect x="30" y="384" width="140" height="12" rx="1" />
        <path d="M86 244 C82 280 84 320 84 362 L96 362 C96 330 98 290 100 252 Z" />
        <path d="M104 250 C110 284 116 320 118 362 L130 362 C128 322 122 282 116 244 Z" />
        <path d="M80 362 L100 362 L102 371 L78 371 Z" /><path d="M114 362 L136 364 L140 371 L112 371 Z" />
        <path d="M82 122 C78 160 76 210 80 252 L122 252 C124 210 122 160 118 122 Z" />
        <path d="M82 126 C72 150 70 176 74 200 L84 198 C82 176 86 152 92 134 Z" /><circle cx="79" cy="203" r="6" />
        <path d="M118 126 C130 132 140 146 146 160 L154 154 C148 140 136 124 122 118 Z" /><circle cx="151" cy="158" r="6.2" />
        <rect x="94" y="96" width="12" height="24" />
        <path d="M90 74 C90 62 106 58 113 66 L116 76 L121 80 L117 83 L118 88 L113 91 C110 96 102 98 96 96 C90 92 88 84 90 74 Z" />
        <path d="M100 92 C104 100 112 108 119 106 C117 98 115 92 113 88 Z" />
        <ellipse cx="102" cy="68" rx="29" ry="5" /><path d="M88 68 C88 51 116 49 116 68 Z" />
        <rect x="150" y="46" width="3.4" height="190" /><circle cx="151.7" cy="40" r="5" />
        <path d="M151.7 48 L134 38 L139 49 L130 50 L151.7 58 Z M151.7 48 L169 38 L164 49 L173 50 L151.7 58 Z" />
      </g>
      <g fill="none" stroke="currentColor" strokeWidth="2.8">
        <path d="M151.7 64 C163 74 163 84 151.7 94 C140 104 140 114 151.7 124 C163 134 163 144 151.7 154" />
        <path d="M151.7 64 C140 74 140 84 151.7 94 C163 104 163 114 151.7 124 C140 134 140 144 151.7 154" />
      </g>
      <g className={styles.flap} style={{ transformOrigin: "114px 64px" }}><path d="M114 64 L136 46 L130 57 L142 53 L128 67 Z" fill="#C2561C" /></g>
      <g className={styles.flap} style={{ transformOrigin: "134px 364px", animationDelay: ".25s" }}><path d="M134 364 L152 350 L147 359 L157 356 L145 368 Z" fill="#C2561C" /></g>
      <g fill="none" stroke="var(--inc)" strokeWidth="1.2" strokeLinecap="round">
        <path d="M80 160 L122 160 M80 246 L86 240 L92 246 L98 240 L104 246 L110 240 L116 246 L122 240 M92 166 L90 238 M102 166 L102 238 M112 166 L114 238" />
        <path d="M106 75 q3 -2 6 0 M104 96 L114 104 M106 100 L116 106 M76 68 L128 68" />
      </g>
    </svg>
  );
}

export function TrojanHorse({ className, width = 270, height = 248 }: FigureProps) {
  const wheel = (cx: number) => (
    <g key={cx} className={styles.spin} style={{ transformOrigin: `${cx}px 194px` }}>
      <circle cx={cx} cy="194" r="13" fill="currentColor" />
      <path
        d={`M${cx} 183 L${cx} 205 M${cx - 11} 194 L${cx + 11} 194 M${cx - 8} 186 L${cx + 8} 202 M${cx + 8} 186 L${cx - 8} 202`}
        fill="none"
        stroke="var(--inc)"
        strokeWidth="1.4"
      />
    </g>
  );
  return (
    <svg viewBox="0 0 240 220" width={width} height={height} className={className} aria-hidden="true" focusable="false">
      <g className={styles.rock} style={{ transformOrigin: "120px 186px" }}>
        <g fill="currentColor">
          <rect x="22" y="174" width="186" height="10" rx="2" />
          <path d="M46 126 L58 126 L58 176 L46 176 Z M70 126 L82 126 L82 176 L70 176 Z M144 126 L156 126 L156 176 L144 176 Z M166 126 L178 126 L178 176 L166 176 Z" />
          <rect x="38" y="84" width="152" height="54" rx="14" />
          <path d="M150 92 L168 30 L194 36 L178 100 Z" />
          <path d="M166 26 C176 16 200 20 216 40 L220 52 C214 58 202 56 194 52 L176 46 Z" />
          <path d="M170 26 L174 6 L183 24 Z" />
          <path d="M42 92 C20 100 16 126 24 152 L31 150 C27 128 31 110 46 104 Z" />
          <path d="M168 34 L160 32 L165 42 L156 42 L162 52 L153 54 L158 64 L150 68 L156 76 L148 82 L154 90 Z" />
        </g>
        <g fill="none" stroke="var(--inc)" strokeWidth="1.2" strokeLinecap="round" opacity=".75">
          <path d="M44 98 L184 98 M40 111 L188 111 M42 124 L186 124 M158 52 L184 58 M155 66 L181 72 M152 80 L178 86" />
          <path d="M52 132 L52 170 M76 132 L76 170 M150 132 L150 170 M172 132 L172 170 M46 152 L82 136 M144 152 L178 136" />
          <circle cx="204" cy="36" r="3" />
        </g>
        <rect className={styles.pulse} x="102" y="104" width="26" height="22" rx="2" fill="#7A3A1C" />
      </g>
      {[50, 96, 142, 186].map(wheel)}
    </svg>
  );
}

export function Wolf({ className, width = 250, height = 208 }: FigureProps) {
  return (
    <svg viewBox="0 0 240 200" width={width} height={height} className={className} aria-hidden="true" focusable="false">
      <g fill="currentColor">
        <path d="M8 198 L40 178 L120 172 L202 176 L234 198 Z" />
        <g className={styles.tail} style={{ transformOrigin: "62px 114px" }}>
          <path d="M62 110 C38 112 20 128 18 158 C24 152 30 150 36 150 C32 160 34 168 38 174 C44 154 54 140 66 130 Z" />
        </g>
        <g className={styles.breath} style={{ transformOrigin: "120px 116px" }}>
          <path d="M58 116 C64 92 104 84 150 88 C170 90 182 100 184 116 C184 132 168 140 140 142 L96 142 C76 142 60 134 58 116 Z" />
          <path d="M150 90 C164 80 172 74 180 70 L192 110 C186 128 172 136 160 138 Z" />
        </g>
        <path d="M164 132 C168 148 170 162 172 178 L182 178 C180 162 178 146 176 130 Z" />
        <path d="M148 134 C150 150 150 164 150 178 L160 178 C160 162 160 148 160 132 Z" />
        <path d="M72 128 C62 140 60 150 66 160 C68 166 64 172 60 178 L72 178 C78 170 80 160 78 152 C80 144 84 138 88 134 Z" />
        <path d="M90 136 C92 148 94 160 94 178 L104 178 C106 160 104 146 102 138 Z" />
        <path d="M170 94 C172 76 178 62 188 54 C196 50 206 52 214 58 C222 62 230 66 234 72 C233 78 226 81 214 81 L206 82 C200 88 194 98 188 110 Z" />
        <g className={styles.ear} style={{ transformOrigin: "196px 56px" }}><path d="M186 56 L190 36 L198 52 Z M196 54 L204 36 L207 56 Z" /></g>
      </g>
      <circle className={styles.pulse} cx="214" cy="64" r="3.4" fill="#D9A07E" />
      <g fill="none" stroke="var(--inc)" strokeWidth="1.1" strokeLinecap="round" opacity=".8">
        <path d="M176 84 l6 10 M172 94 l6 10 M168 104 l6 10 M180 74 l6 10 M80 136 Q110 144 140 136 M208 64 q4 -3 9 0 M226 72 l6 1 M214 78 q8 2 16 -1" />
      </g>
    </svg>
  );
}

export function TreeOfLife({ className, width = 28, height = 34 }: FigureProps) {
  return (
    <svg viewBox="0 0 200 240" width={width} height={height} className={className} aria-hidden="true" focusable="false">
      <circle cx="100" cy="22" r="10" fill="#C2561C" />
      <path d="M94 204 L91 118 L109 118 L106 204 Z" fill="currentColor" />
      <g fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round">
        <path d="M100 152 C80 142 66 126 60 106" /><path d="M100 152 C120 142 134 126 140 106" />
        <path d="M100 130 C86 118 80 100 82 80" /><path d="M100 130 C114 118 120 100 118 80" />
        <path d="M100 122 L100 62" /><path d="M96 206 C82 214 66 218 48 226" /><path d="M104 206 C118 214 134 218 152 226" />
      </g>
      <g fill="currentColor">
        <circle cx="60" cy="100" r="15" /><circle cx="140" cy="100" r="15" /><circle cx="82" cy="74" r="13" />
        <circle cx="118" cy="74" r="13" /><circle cx="100" cy="54" r="15" />
      </g>
    </svg>
  );
}
