/**
 * The sail mark, logo v4 (see DESIGN.md → Brand layer → Logo).
 *
 * Yard and mast draw a T, the name's initial. The mast stays behind the
 * opaque sail, so the sail stays in front. Straight
 * luff, leech bellied by wind from the left, a pennant at the masthead; the
 * sail's foot is the cash curve. Below 32 px use `small`: heavier mast and
 * yard, no pennant, no shading.
 */
type SailMarkProps = {
  size?: number;
  small?: boolean;
  /** Sail colour. Defaults to the light-ground ember. */
  ember?: string;
  className?: string;
  title?: string;
};

export function SailMark({ size = 32, small = false, ember = "#C2561C", className, title }: SailMarkProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {small ? (
        <>
          <line x1="100" y1="10" x2="100" y2="188" stroke="currentColor" strokeWidth="20" />
          <path
            d="M30 52 L170 45 Q190 96 160 148 C148 152 138 176 122 178 C102 180 74 148 42 142 Q30 94 30 52 Z"
            fill={ember}
          />
          <path d="M18 51 L182 40" stroke="currentColor" strokeWidth="19" />
        </>
      ) : (
        <>
          <line x1="100" y1="13" x2="100" y2="188" stroke="currentColor" strokeWidth="11" strokeLinecap="round" />
          <path d="M105 13 L134 19.5 L105 26 Z" fill="currentColor" />
          <path
            d="M34 45 L168 41 Q186 94 158 146 C146 150 136 176 122 178 C104 180 76 146 44 138 Q34 92 34 45 Z"
            fill={ember}
          />
          {/* The sail is opaque. Shade follows the wind: a crescent on the bellied leech, a band under the yard. */}
          <path
            d="M150 41.5 L168 41 Q186 94 158 146 C146 150 136 176 122 178 C136 166 152 140 156 108 Q160 74 150 41.5 Z"
            fill="#000"
            opacity={0.2}
          />
          <path d="M34 45 L168 41 L168 48 Q100 50 34 53 Z" fill="#000" opacity={0.14} />
          <path d="M21 39 Q100 29.5 179 34.5 L179 40.5 Q100 44.5 21 46 Z" fill="currentColor" />
        </>
      )}
    </svg>
  );
}
