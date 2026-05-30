// 36px bottom dock — peek into the Vault.
// Ported from donnaai/project/archive.jsx:2-22.
//
// All counts are hardcoded for v1 because the Vault model isn't built
// yet. Any click anywhere on the dock routes to /vault, which renders
// ComingSoon — so this is purely a visual rhythm element matching the
// design.

import { useNavigate } from "react-router-dom";

import { Ic } from "../Ui/Ic";

interface DockTag {
  label: string;
  count: string;
}

const TAGS: DockTag[] = [
  { label: "Decisions", count: "42" },
  { label: "Docs", count: "218" },
  { label: "Links", count: "93" },
  { label: "Files", count: "1.4k" },
  { label: "Old channels", count: "17" },
  { label: "Agent runs", count: "3.2k" },
];

export default function ArchiveDock() {
  const navigate = useNavigate();
  const open = () => navigate("/vault");

  return (
    <footer
      className="[grid-area:archive] flex items-center px-[14px] gap-[14px] bg-bg-1 border-t border-border-soft text-[12px] overflow-hidden"
      aria-label="Vault dock"
    >
      <button
        type="button"
        className="flex items-center gap-1.5 text-text-2 font-medium hover:text-text-0"
        onClick={open}
        aria-label="Open vault"
      >
        <span className="inline-grid place-items-center w-3.5 h-3.5 text-text-3">
          <Ic.archive />
        </span>
        <span>Vault</span>
      </button>
      <div className="flex gap-1.5 items-center flex-1 min-w-0" role="list">
        {TAGS.map((t) => (
          <button
            key={t.label}
            type="button"
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-bg-2 border border-border-soft text-[11px] text-text-2 whitespace-nowrap hover:bg-bg-3 hover:text-text-0"
            onClick={open}
            role="listitem"
          >
            <span>{t.label}</span>
            <span className="text-text-3 font-mono">{t.count}</span>
          </button>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-2.5">
        <span className="text-ai text-[11.5px]">
          ✦ 3 resurfaced for you
        </span>
        <button
          type="button"
          className="text-text-2 text-[11.5px] px-2 py-1 rounded-md hover:bg-bg-2 hover:text-text-0"
          onClick={open}
        >
          Open vault →
        </button>
      </div>
    </footer>
  );
}
