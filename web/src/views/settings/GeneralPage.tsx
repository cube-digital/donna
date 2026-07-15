// Ported from assets/donna-ui-kit/react/GeneralPage.jsx — workspace general
// settings. Inputs are CONTROLLED so onSave can hand a patch to the container.
import { useState } from "react";

import type { KitWorkspace } from "./types";

export interface GeneralPageProps {
  workspace: KitWorkspace;
  role?: string;
  onSave?: (patch: {
    name: string;
    slug: string;
    primary_domain: string;
  }) => void;
  onDelete?: () => void;
}

export default function GeneralPage({
  workspace,
  role = "owner",
  onSave,
  onDelete,
}: GeneralPageProps) {
  const canEdit = role === "owner" || role === "admin";
  const [name, setName] = useState(workspace.name ?? "");
  const [slug, setSlug] = useState(workspace.slug ?? "");
  const [primaryDomain, setPrimaryDomain] = useState(
    workspace.primary_domain ?? "",
  );

  return (
    <>
      <div className="dn-grid-2">
        <div>
          <div className="dn-field">
            <div className="dn-label">Workspace name</div>
            <input
              className="dn-input"
              value={name}
              disabled={!canEdit}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="dn-field">
            <div className="dn-label">Workspace URL</div>
            <input
              className="dn-input"
              value={slug}
              disabled={!canEdit}
              onChange={(e) => setSlug(e.target.value)}
            />
            <div className="dn-hint">Changing this breaks existing links.</div>
          </div>
          <div className="dn-field">
            <div className="dn-label">Primary domain</div>
            <input
              className="dn-input"
              value={primaryDomain}
              disabled={!canEdit}
              onChange={(e) => setPrimaryDomain(e.target.value)}
            />
            <div className="dn-hint">
              People with this email domain are treated as internal — Donna files
              their meetings and emails under your workspace, not under a client
              org.
            </div>
          </div>
        </div>
        <div style={{ width: 200 }}>
          <div className="dn-section">Icon</div>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div className="dn-square">{workspace.name?.[0]}</div>
            {canEdit && <button className="dn-mini">Change</button>}
          </div>
          <div className="dn-section">Your role</div>
          <span className="dn-chip dn-chip--grape">{role}</span>
        </div>
      </div>

      {canEdit && (
        <div style={{ display: "flex", gap: 9, margin: "6px 0 20px" }}>
          <button
            className="dn-btn dn-btn--primary"
            onClick={() =>
              onSave?.({ name, slug, primary_domain: primaryDomain })
            }
          >
            Save changes
          </button>
          <button className="dn-btn dn-btn--ghost">Cancel</button>
        </div>
      )}

      {role === "owner" && (
        <>
          <div className="dn-section" style={{ color: "var(--dn-danger)" }}>
            Danger zone
          </div>
          <div className="dn-danger-zone">
            <div>
              <div className="dn-name" style={{ color: "var(--dn-danger)" }}>
                Delete this workspace
              </div>
              <div className="dn-meta">
                Permanently removes all channels, documents and cortex memory.
              </div>
            </div>
            <button
              className="dn-btn dn-btn--danger dn-spacer"
              onClick={onDelete}
            >
              Delete
            </button>
          </div>
        </>
      )}
    </>
  );
}
