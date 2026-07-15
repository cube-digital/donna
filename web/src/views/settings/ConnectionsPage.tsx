// Ported from assets/donna-ui-kit/react/ConnectionsPage.jsx — connected +
// available integrations, mapped from the integrations store by the container.
import Icon from "../../components/kit/Icon";
import type { KitConnector } from "./types";

export interface ConnectionsPageProps {
  connectors?: KitConnector[];
  onConnect?: (slug: string) => void;
  onConfigure?: (slug: string) => void;
  onDisconnect?: (slug: string) => void;
}

export default function ConnectionsPage({
  connectors = [],
  onConnect,
  onConfigure,
  onDisconnect,
}: ConnectionsPageProps) {
  const connected = connectors.filter((c) => c.status === "live");
  const available = connectors.filter((c) => c.status !== "live");
  return (
    <>
      <div className="dn-section">Connected · {connected.length}</div>
      {connected.map((c) => (
        <div className="dn-row" key={c.slug}>
          <span className="dn-avatar" style={{ background: c.tint, color: c.color }}>
            <Icon name={c.icon} size={18} />
          </span>
          <div>
            <div className="dn-name">{c.name}</div>
            <div className="dn-meta">
              {c.description}
              {c.cortex_path ? (
                <>
                  {" "}
                  → <span className="dn-mono">{c.cortex_path}</span>
                </>
              ) : null}
              {c.last_sync ? ` · synced ${c.last_sync}` : ""}
            </div>
          </div>
          <div className="dn-actions">
            <span className="dn-chip dn-chip--ok">live</span>
            <button className="dn-mini" onClick={() => onConfigure?.(c.slug)}>
              Configure
            </button>
            <button
              className="dn-mini dn-mini--danger"
              onClick={() => onDisconnect?.(c.slug)}
            >
              Disconnect
            </button>
          </div>
        </div>
      ))}

      <div className="dn-section">Available</div>
      {available.map((c) => (
        <div className="dn-row dn-row--dashed" key={c.slug}>
          <span className="dn-avatar dn-avatar--empty">
            <Icon name={c.icon} size={18} />
          </span>
          <div>
            <div className="dn-name">{c.name}</div>
            <div className="dn-meta">
              {c.description}
              {c.cortex_path ? (
                <>
                  {" "}
                  → <span className="dn-mono">{c.cortex_path}</span>
                </>
              ) : null}
            </div>
          </div>
          <button
            className="dn-btn dn-btn--primary dn-spacer"
            onClick={() => onConnect?.(c.slug)}
          >
            Connect
          </button>
        </div>
      ))}
    </>
  );
}
