// Client-side derivation of avatar initials + a deterministic colour hue,
// used by the ported donna-ui-kit surfaces (Settings, ChannelPanel) that
// expect a `{ initials, color }` on each member/candidate row.

/** Two-letter initials from a display name (or "?" when empty). */
export function initialsFrom(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Deterministic hash → oklch colour string, stable per key (e.g. user id). */
export function colorFrom(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = (h * 31 + key.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  return `oklch(0.60 0.17 ${hue})`;
}
