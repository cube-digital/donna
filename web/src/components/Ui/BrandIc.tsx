// Brand glyphs for connected integrations. Inline SVG so they stay sharp at
// 18-20px sidebar sizes and inherit our color tokens where useful.
//
// Logos kept intentionally simplified (recognizable but not pixel-perfect
// vendor marks) — swap with official brand assets when a design pass lands.

import { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement>;

export function GmailIc(props: Props) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" {...props}>
      <rect x="2" y="5" width="20" height="14" rx="2.2" fill="#fff" />
      <path d="M2 7.3l10 6.7 10-6.7v-.6A2 2 0 0 0 20 4.7H4A2 2 0 0 0 2 6.7v.6z" fill="#EA4335" />
      <path d="M2 19V8.5l4.2 2.8V19H2z" fill="#4285F4" />
      <path d="M22 19V8.5l-4.2 2.8V19H22z" fill="#34A853" />
      <path d="M6.2 19v-7.7L12 15l5.8-3.7V19h-2.2v-4.4L12 16.9 8.4 14.6V19H6.2z" fill="#C5221F" />
    </svg>
  );
}

export function DriveIc(props: Props) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" {...props}>
      <path d="M7.6 3.2L1.3 14l3.7 6.4 6.3-10.8L7.6 3.2z" fill="#0F9D58" />
      <path d="M22.7 14L16.4 3.2H7.6L13.9 14h8.8z" fill="#FFC107" />
      <path d="M5 20.4h14L22.7 14H8.7l-3.7 6.4z" fill="#4285F4" />
    </svg>
  );
}

export function FathomIc(props: Props) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" {...props}>
      <rect width="24" height="24" rx="5" fill="#1A56DB" />
      <path
        d="M5 14.5c2-3 4-3 6 0s4 3 6 0M5 10.5c2-3 4-3 6 0s4 3 6 0"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

// Generic fallback for any unknown slug — first two letters in a square.
export function InitialsIc({ label, ...props }: Props & { label: string }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" {...props}>
      <rect width="24" height="24" rx="5" className="fill-bg-3" />
      <text
        x="12"
        y="15.5"
        textAnchor="middle"
        className="fill-text-1"
        fontSize="9.5"
        fontWeight="600"
        fontFamily="ui-sans-serif, system-ui"
      >
        {label.slice(0, 2).toUpperCase()}
      </text>
    </svg>
  );
}

// Single dispatcher by connector slug — keeps callers free of brand lookups.
export function ConnectorIcon({ slug, label }: { slug: string; label: string }) {
  switch (slug) {
    case "gmail":  return <GmailIc />;
    case "drive":  return <DriveIc />;
    case "fathom": return <FathomIc />;
    default:       return <InitialsIc label={label} />;
  }
}
