// Stable per-agent hue mapper.
//
// Mirrors the logic used by Channel/Message.tsx so that the same agent
// always lights up with the same colour everywhere it appears (sidebar
// row, personal chat-head, message avatar, …). The design clamps
// agents to the violet → indigo family (260..319) so they read as "AI"
// at a glance.
//
// Pure / no state — safe to call on every render.

export function hueForAgent(id: string | undefined): number {
  if (!id) return 282;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return 260 + (h % 60);
}
