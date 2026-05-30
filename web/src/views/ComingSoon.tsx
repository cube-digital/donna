// Used by Vault, Profile, Search, Workspace, Empty-channel routes —
// surfaces we haven't built yet but want reachable from the design's nav.
// Re-creates the design's empty-state chrome (icon, title, sub) with
// Tailwind utilities so the page still reads as intentional, not broken.

interface ComingSoonProps {
  title?: string;
  sub?: string;
}

export default function ComingSoon({
  title = "Coming soon",
  sub = "This surface is part of the DonnaAI design but isn't wired to the backend yet.",
}: ComingSoonProps) {
  return (
    <div className="overflow-y-auto px-8 py-6 h-full">
      <div className="flex flex-col items-center justify-center h-full text-text-3 gap-3 p-10 text-center">
        <div className="inline-grid place-items-center w-14 h-14 rounded-xl bg-bg-2 text-text-3">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="21 8 21 21 3 21 3 8" />
            <rect x="1" y="3" width="22" height="5" />
            <line x1="10" y1="12" x2="14" y2="12" />
          </svg>
        </div>
        <div className="text-sm text-text-1 font-medium">{title}</div>
        <div className="text-[12.5px] text-text-3 max-w-[280px] leading-[1.5]">
          {sub}
        </div>
      </div>
    </div>
  );
}
