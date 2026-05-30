// Goofy icon set — every glyph is a single SVG that paints with
// `currentColor`. Components compose these via `<GlyphSlot name="…"/>`
// so the call site can stay terse.
//
// Icons match the design source 1:1; extras (link, share, etc.) come
// from the existing Donna icon set so the library can be a drop-in
// replacement for the older `Ic` namespace.

import type { ComponentType, SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

const baseProps: Partial<IconProps> = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

function Svg({
  children,
  strokeWidth = 1.8,
  "aria-hidden": ariaHidden = true,
  focusable = false,
  ...rest
}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      strokeWidth={strokeWidth}
      // Inline-SVG icons are decorative by default — they live inside a
      // <button> / <a> / row that already carries the accessible name
      // (aria-label / surrounding text). Hiding the SVG from AT prevents
      // double-announcement. Callers using an icon as the *only* visible
      // content of a non-labelled element can opt back in by passing
      // aria-hidden={false} + a role/aria-label.
      aria-hidden={ariaHidden}
      focusable={focusable}
      {...baseProps}
      {...rest}
    >
      {children}
    </svg>
  );
}

export const Hash = (p: IconProps) => (
  <Svg strokeWidth={2} {...p}>
    <line x1="4" y1="9" x2="20" y2="9" />
    <line x1="4" y1="15" x2="20" y2="15" />
    <line x1="10" y1="3" x2="8" y2="21" />
    <line x1="16" y1="3" x2="14" y2="21" />
  </Svg>
);
export const Search = (p: IconProps) => (
  <Svg strokeWidth={2} {...p}>
    <circle cx="11" cy="11" r="7" />
    <line x1="20" y1="20" x2="16.5" y2="16.5" />
  </Svg>
);
export const Plus = (p: IconProps) => (
  <Svg strokeWidth={2.2} {...p}>
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </Svg>
);
export const Check = (p: IconProps) => (
  <Svg strokeWidth={3} {...p}>
    <polyline points="20 6 9 17 4 12" />
  </Svg>
);
export const X = (p: IconProps) => (
  <Svg strokeWidth={2.4} {...p}>
    <line x1="6" y1="6" x2="18" y2="18" />
    <line x1="18" y1="6" x2="6" y2="18" />
  </Svg>
);
export const Send = (p: IconProps) => (
  <Svg strokeWidth={2} {...p}>
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </Svg>
);
export const Sparkle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" />
  </Svg>
);
export const Bolt = (p: IconProps) => (
  <Svg {...p}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </Svg>
);
export const Brain = (p: IconProps) => (
  <Svg strokeWidth={1.7} {...p}>
    <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15A2.5 2.5 0 0 1 7 19c-2 0-3.5-2-3.5-4 0-1 .5-2 1.5-2.5C4 11.5 4 9.5 5 8.5c-.5-1 0-3 2-3.5A2.5 2.5 0 0 1 9.5 2z" />
    <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15A2.5 2.5 0 0 0 17 19c2 0 3.5-2 3.5-4 0-1-.5-2-1.5-2.5 1-1 1-3 0-4 .5-1 0-3-2-3.5A2.5 2.5 0 0 0 14.5 2z" />
  </Svg>
);
export const Doc = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="8" y1="13" x2="16" y2="13" />
    <line x1="8" y1="17" x2="13" y2="17" />
  </Svg>
);
export const Smile = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8 14s1.5 2 4 2 4-2 4-2" />
    <line x1="9" y1="9" x2="9.01" y2="9" />
    <line x1="15" y1="9" x2="15.01" y2="9" />
  </Svg>
);
export const Reply = (p: IconProps) => (
  <Svg {...p}>
    <polyline points="9 17 4 12 9 7" />
    <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
  </Svg>
);
export const More = (p: IconProps) => (
  <Svg strokeWidth={2} {...p}>
    <circle cx="5" cy="12" r="1.4" />
    <circle cx="12" cy="12" r="1.4" />
    <circle cx="19" cy="12" r="1.4" />
  </Svg>
);
export const Edit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
  </Svg>
);
export const Trash = (p: IconProps) => (
  <Svg {...p}>
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
  </Svg>
);
export const Pin = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 17v5" />
    <path d="M9 10.8V4h6v6.8l2 3.2H7z" />
  </Svg>
);
export const Share = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" />
    <line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
  </Svg>
);
export const Link = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" />
    <path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19" />
  </Svg>
);
export const Bell = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.7 21a2 2 0 0 1-3.4 0" />
  </Svg>
);
export const At = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />
  </Svg>
);
export const Sun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <line x1="12" y1="2" x2="12" y2="4" />
    <line x1="12" y1="20" x2="12" y2="22" />
    <line x1="4.9" y1="4.9" x2="6.3" y2="6.3" />
    <line x1="17.7" y1="17.7" x2="19.1" y2="19.1" />
    <line x1="2" y1="12" x2="4" y2="12" />
    <line x1="20" y1="12" x2="22" y2="12" />
    <line x1="4.9" y1="19.1" x2="6.3" y2="17.7" />
    <line x1="17.7" y1="6.3" x2="19.1" y2="4.9" />
  </Svg>
);
export const Moon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </Svg>
);
export const Home = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 11l9-8 9 8v9a2 2 0 0 1-2 2h-4v-7H9v7H5a2 2 0 0 1-2-2z" />
  </Svg>
);
export const Msg = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 11.5a8.5 8.5 0 0 1-12.7 7.4L3 21l1.5-4.7A8.5 8.5 0 1 1 21 11.5z" />
  </Svg>
);
export const File = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </Svg>
);
export const Folder = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
  </Svg>
);
export const Star = (p: IconProps) => (
  <Svg {...p}>
    <polygon points="12 2 15 9 22 9.3 17 14 18.5 21 12 17.3 5.5 21 7 14 2 9.3 9 9 12 2" />
  </Svg>
);
export const Caret = (p: IconProps) => (
  <Svg strokeWidth={2.5} {...p}>
    <polyline points="6 9 12 15 18 9" />
  </Svg>
);
export const Lock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Svg>
);
export const Thread = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 11.5a8.5 8.5 0 0 1-12.7 7.4L3 21l1.5-4.7A8.5 8.5 0 1 1 21 11.5z" />
    <line x1="8" y1="9" x2="16" y2="9" />
    <line x1="8" y1="13" x2="13" y2="13" />
  </Svg>
);
export const Archive = (p: IconProps) => (
  <Svg strokeWidth={1.7} {...p}>
    <polyline points="21 8 21 21 3 21 3 8" />
    <rect x="1" y="3" width="22" height="5" />
    <line x1="10" y1="12" x2="14" y2="12" />
  </Svg>
);

/**
 * Namespaced lookup matching the design source's `GIc` object. Useful
 * when you only know the icon by name (`GMenuItem icon="reply"`); for
 * static call sites, prefer the named imports above so tree-shaking
 * can drop unused icons.
 */
export const GIc = {
  hash: Hash,
  search: Search,
  plus: Plus,
  check: Check,
  x: X,
  send: Send,
  sparkle: Sparkle,
  bolt: Bolt,
  brain: Brain,
  doc: Doc,
  smile: Smile,
  reply: Reply,
  more: More,
  edit: Edit,
  trash: Trash,
  pin: Pin,
  share: Share,
  link: Link,
  bell: Bell,
  at: At,
  sun: Sun,
  moon: Moon,
  home: Home,
  msg: Msg,
  file: File,
  folder: Folder,
  star: Star,
  caret: Caret,
  lock: Lock,
  thread: Thread,
  archive: Archive,
} as const;

export type IconName = keyof typeof GIc;

interface GlyphSlotProps extends Omit<IconProps, "width" | "height"> {
  name: IconName;
  size?: number;
}

/**
 * Render one icon by name + size. Identical to the design source's
 * `<GlyphSlot/>`; prefer the named imports when the icon is static so
 * the bundler can drop unused entries.
 */
export function GlyphSlot({ name, size = 16, ...rest }: GlyphSlotProps) {
  const IconCmp = GIc[name] as ComponentType<IconProps>;
  return <IconCmp width={size} height={size} {...rest} />;
}
