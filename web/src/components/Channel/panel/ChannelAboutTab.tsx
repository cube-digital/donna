// Ported from assets/donna-ui-kit/react/ChannelAboutTab.jsx.
import type { KitArtifacts, KitChannel } from "./types";

export interface ChannelAboutTabProps {
  channel: KitChannel;
  artifacts?: Partial<KitArtifacts>;
  onOpenFiles?: () => void;
}

export default function ChannelAboutTab({
  channel,
  artifacts = {},
  onOpenFiles,
}: ChannelAboutTabProps) {
  return (
    <>
      <div className="dn-section">About</div>
      <div className="dn-row">
        <div>
          <div className="dn-name">Topic</div>
          <div className="dn-meta">{channel.topic || "No topic yet"}</div>
        </div>
        <button className="dn-mini dn-spacer">Edit</button>
      </div>
      <div className="dn-row">
        <div>
          <div className="dn-name">Created</div>
          <div className="dn-meta">
            by {channel.created_by} · {channel.created_at}
          </div>
        </div>
      </div>
      <div className="dn-row">
        <div>
          <div className="dn-name">Files &amp; docs</div>
          <div className="dn-meta">
            {artifacts.drafts ?? 0} draft · {artifacts.finalized ?? 0} finalized
          </div>
        </div>
        <button
          className="dn-mini dn-mini--grape dn-spacer"
          onClick={onOpenFiles}
        >
          Open files
        </button>
      </div>

      <div className="dn-section" style={{ marginTop: 18 }}>
        Pinned
      </div>
      <div className="dn-row dn-row--dashed">
        <div className="dn-meta">
          Nothing pinned yet — pin a message to keep it at the top.
        </div>
      </div>
    </>
  );
}
