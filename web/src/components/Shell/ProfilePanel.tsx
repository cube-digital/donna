// Global profile panel — a right-side drawer opened from the WsRail avatar
// pill. Ported from assets/donna-ui-kit/react/ProfileDrawer.jsx onto the
// real /me store: edit display name + status, set yourself active/away,
// upload/remove a profile picture, and sign out. Renders nothing when closed.
//
// `UserAvatar` is still exported from this module (WsRail imports it).

import { useEffect, useRef, useState } from "react";

import "../../styles/donna-kit.css";
import { deletePicture, updateMe, uploadPicture } from "../../api/users";
import { GAvatar } from "../Goofy";
import Icon from "../kit/Icon";
import { initialsFrom } from "../../lib/kitAvatar";
import { useAuth } from "../../state/auth";
import { useMe } from "../../state/me";
import { useProfilePanel } from "../../state/profilePanel";

/** Picture when set, coloured initials otherwise — with an optional
 *  active/away presence dot in the corner. */
export function UserAvatar({
  pictureUrl,
  name,
  sizePx = 40,
  isAway,
  showDot = false,
}: {
  pictureUrl?: string | null;
  name?: string;
  sizePx?: number;
  isAway?: boolean;
  showDot?: boolean;
}) {
  const inner = pictureUrl ? (
    <img
      src={pictureUrl}
      alt={name || "Profile picture"}
      className="rounded-[12px] border border-border-soft object-cover"
      style={{ width: sizePx, height: sizePx }}
    />
  ) : (
    <GAvatar
      name={name || "?"}
      size={sizePx >= 48 ? "xl" : sizePx >= 40 ? "lg" : "md"}
    />
  );
  if (!showDot) return inner;
  const dotPx = Math.max(9, Math.round(sizePx * 0.28));
  return (
    <span className="relative inline-flex shrink-0">
      {inner}
      <span
        title={isAway ? "Away" : "Active"}
        className={
          "absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-bg-1 " +
          (isAway ? "bg-text-4" : "bg-ok")
        }
        style={{ width: dotPx, height: dotPx }}
      />
    </span>
  );
}

const PRESETS = ["🎯 Focusing", "📅 In a meeting", "🌴 OOO"];

export default function ProfileDrawer() {
  const open = useProfilePanel((s) => s.open);
  const close = useProfilePanel((s) => s.closePanel);
  const me = useMe((s) => s.me);
  const setMe = useMe((s) => s.setMe);
  const load = useMe((s) => s.load);
  const signOut = useAuth((s) => s.signOut);

  const [active, setActive] = useState(true);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  // Seed local state from the profile whenever it changes.
  useEffect(() => {
    if (me) {
      setName(me.full_name ?? "");
      setStatus(me.status ?? "");
      setActive(!me.is_away);
    }
  }, [me]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const displayName = me?.full_name || me?.email || "You";
  const initials = initialsFrom(displayName);

  async function save() {
    setSaving(true);
    try {
      setMe(await updateMe({ full_name: name.trim(), status, is_away: !active }));
    } catch {
      /* leave fields as-is on failure */
    } finally {
      setSaving(false);
    }
  }

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      setMe(await uploadPicture(file));
    } catch {
      /* ignore */
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removePicture() {
    setUploading(true);
    try {
      setMe(await deletePicture());
    } catch {
      /* ignore */
    } finally {
      setUploading(false);
    }
  }

  function onSignOut() {
    close();
    signOut();
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex justify-end"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex-1 bg-[oklch(0.26_0.03_285/0.30)]"
        onClick={close}
        aria-hidden
      />
      <aside
        className="dn-root dn-drawer dn-paper h-full"
        style={{ boxShadow: "-8px 0 24px oklch(0.26 0.03 285 / 0.18)" }}
      >
        <div className="dn-drawer-head">
          Profile
          <button
            type="button"
            aria-label="Close"
            onClick={close}
            className="dn-spacer"
            style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "var(--dn-t4)" }}
          >
            <Icon name="x" />
          </button>
        </div>

        <div className="dn-drawer-body">
          <div className="dn-row dn-row--outline">
            <span
              className="dn-avatar dn-avatar--lg"
              style={{
                background: me?.picture_url ? "transparent" : "var(--dn-coral)",
                overflow: "hidden",
              }}
            >
              {me?.picture_url ? (
                <img
                  src={me.picture_url}
                  alt={displayName}
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
              ) : (
                initials
              )}
              {active && <span className="dn-presence" />}
            </span>
            <div>
              <div className="dn-name">{displayName}</div>
              <div className="dn-meta">{me?.email}</div>
              <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
                <span
                  className="dn-link"
                  role="button"
                  tabIndex={0}
                  onClick={() => fileRef.current?.click()}
                >
                  {uploading ? "Uploading…" : me?.picture_url ? "Change" : "Add picture"}
                </span>
                {me?.picture_url ? (
                  <span
                    className="dn-link"
                    role="button"
                    tabIndex={0}
                    style={{ color: "var(--dn-t4)" }}
                    onClick={removePicture}
                  >
                    Remove
                  </span>
                ) : null}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                style={{ display: "none" }}
                onChange={onPickFile}
              />
            </div>
          </div>

          <div className="dn-row dn-row--outline">
            <span
              style={{
                width: 9,
                height: 9,
                borderRadius: "50%",
                flex: "none",
                background: active ? "var(--dn-ok)" : "var(--dn-t4)",
              }}
            />
            <div>
              <div className="dn-name">{active ? "Active" : "Away"}</div>
              <div className="dn-meta">
                {active ? "Shown as active" : "Shown as away"}
              </div>
            </div>
            <div
              className={`dn-toggle dn-toggle--presence dn-spacer ${active ? "is-on" : ""}`}
              role="switch"
              aria-checked={active}
              onClick={() => setActive((v) => !v)}
            />
          </div>

          <div className="dn-label" style={{ marginTop: 16 }}>
            Display name
          </div>
          <input
            className="dn-input dn-input--profile"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />

          <div className="dn-label" style={{ marginTop: 14 }}>
            Status
          </div>
          <input
            className="dn-input dn-input--profile"
            placeholder="What are you up to?"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          />

          <div className="dn-pill-row" style={{ marginTop: 11 }}>
            {PRESETS.map((p) => (
              <span
                key={p}
                className={`dn-pill ${status === p ? "is-on" : ""}`}
                onClick={() => setStatus(p)}
              >
                {p}
              </span>
            ))}
          </div>

          <button
            className="dn-btn dn-btn--primary dn-btn--profile"
            style={{ marginTop: 16 }}
            disabled={saving}
            onClick={save}
          >
            {saving ? "Saving…" : "Save profile"}
          </button>
        </div>

        <div className="dn-drawer-foot">
          <button
            className="dn-btn dn-btn--ghost dn-btn--profile dn-btn--block"
            onClick={onSignOut}
          >
            Sign out
          </button>
        </div>
      </aside>
    </div>
  );
}
