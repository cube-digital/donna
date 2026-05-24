// Inline-SVG icon set — port of `donnaai/project/ui.jsx` lines 4-130.
//
// Each icon is a tiny stateless React component that accepts any SVG props
// (spread last, so width/height/className/style overrides on the call site
// always win). `currentColor` is used for stroke / fill so the parent's CSS
// `color` controls the visual — matches the design's heavy use of
// `color: var(--text-2)` etc. on icon wrappers.
//
// Two equivalent surfaces:
//   import { Hash } from "./Ic";  →  <Hash />
//   import { Ic } from "./Ic";    →  <Ic.hash />
// The `Ic.<key>` form mirrors the original prototype so call sites in the
// other ports stay copy-pasta-able.

import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

const base: Omit<IconProps, "children"> = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export const Hash = (p: IconProps) => (
  <svg {...base} {...p}>
    <line x1="4" y1="9" x2="20" y2="9" />
    <line x1="4" y1="15" x2="20" y2="15" />
    <line x1="10" y1="3" x2="8" y2="21" />
    <line x1="16" y1="3" x2="14" y2="21" />
  </svg>
);

export const Lock = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);

export const Search = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="11" cy="11" r="7" />
    <line x1="16.5" y1="16.5" x2="21" y2="21" />
  </svg>
);

export const Plus = (p: IconProps) => (
  <svg {...base} {...p}>
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

export const Caret = (p: IconProps) => (
  <svg {...base} {...p}>
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

export const CaretR = (p: IconProps) => (
  <svg {...base} {...p}>
    <polyline points="9 6 15 12 9 18" />
  </svg>
);

export const Home = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 11l9-8 9 8" />
    <path d="M5 10v10a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V10" />
  </svg>
);

export const Msg = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M21 12a8 8 0 0 1-11.5 7.2L4 21l1.8-5.5A8 8 0 1 1 21 12z" />
  </svg>
);

export const Bell = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 7 3 9H3c0-2 3-2 3-9" />
    <path d="M10 21a2 2 0 0 0 4 0" />
  </svg>
);

export const File = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <polyline points="14 3 14 8 19 8" />
  </svg>
);

export const Doc = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <polyline points="14 3 14 8 19 8" />
    <line x1="9" y1="13" x2="15" y2="13" />
    <line x1="9" y1="17" x2="13" y2="17" />
  </svg>
);

export const Link = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
    <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
  </svg>
);

export const Sparkle = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" />
    <path d="M19 14l1 2 2 1-2 1-1 2-1-2-2-1 2-1z" />
  </svg>
);

export const Brain = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 1 5 3 3 0 0 0 4 4 3 3 0 0 0 3-2" />
    <path d="M15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-1 5 3 3 0 0 1-4 4 3 3 0 0 1-3-2" />
    <line x1="12" y1="6" x2="12" y2="20" />
  </svg>
);

export const Bolt = (p: IconProps) => (
  <svg {...base} {...p}>
    <polygon points="13 2 4 14 11 14 10 22 20 10 13 10 14 2 13 2" />
  </svg>
);

export const Smile = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8 14s1.5 2 4 2 4-2 4-2" />
    <line x1="9" y1="10" x2="9.01" y2="10" />
    <line x1="15" y1="10" x2="15.01" y2="10" />
  </svg>
);

export const Send = (p: IconProps) => (
  <svg {...base} {...p}>
    <line x1="21" y1="3" x2="11" y2="13" />
    <polygon points="21 3 14.5 21 11 13 3 9.5 21 3" />
  </svg>
);

export const At = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />
  </svg>
);

export const Star = (p: IconProps) => (
  <svg {...base} {...p}>
    <polygon points="12 2 15 9 22 9.5 17 14.5 18.5 22 12 18 5.5 22 7 14.5 2 9.5 9 9 12 2" />
  </svg>
);

export const More = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="5" cy="12" r="1.2" />
    <circle cx="12" cy="12" r="1.2" />
    <circle cx="19" cy="12" r="1.2" />
  </svg>
);

export const Archive = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="3" y="4" width="18" height="4" rx="1" />
    <path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" />
    <line x1="10" y1="12" x2="14" y2="12" />
  </svg>
);

export const Thread = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M21 11.5a8 8 0 0 1-11.5 7.2L4 20l1.5-4.5A8 8 0 1 1 21 11.5z" />
    <path d="M9 10h6" />
    <path d="M9 13h4" />
  </svg>
);

export const Share = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" />
    <line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
  </svg>
);

export const Sun = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="4" />
    <line x1="12" y1="2" x2="12" y2="4" />
    <line x1="12" y1="20" x2="12" y2="22" />
    <line x1="4" y1="12" x2="2" y2="12" />
    <line x1="22" y1="12" x2="20" y2="12" />
    <line x1="5.6" y1="5.6" x2="4.2" y2="4.2" />
    <line x1="19.8" y1="19.8" x2="18.4" y2="18.4" />
    <line x1="5.6" y1="18.4" x2="4.2" y2="19.8" />
    <line x1="19.8" y1="4.2" x2="18.4" y2="5.6" />
  </svg>
);

export const Edit = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z" />
  </svg>
);

export const Folder = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </svg>
);

// Keyed accessor matching `donnaai/project/ui.jsx` shape so call sites can
// do `<Ic.hash />` like in the prototype.
export const Ic = {
  hash: Hash,
  lock: Lock,
  search: Search,
  plus: Plus,
  caret: Caret,
  caretR: CaretR,
  home: Home,
  msg: Msg,
  bell: Bell,
  file: File,
  doc: Doc,
  link: Link,
  sparkle: Sparkle,
  brain: Brain,
  bolt: Bolt,
  smile: Smile,
  send: Send,
  at: At,
  star: Star,
  more: More,
  archive: Archive,
  thread: Thread,
  share: Share,
  sun: Sun,
  edit: Edit,
  folder: Folder,
} as const;
