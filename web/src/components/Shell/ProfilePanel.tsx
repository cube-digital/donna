// Global profile panel — a right-side drawer opened from the WsRail avatar
// pill. Edit display name + status, set yourself active/away, upload a
// profile picture, and sign out. Reads/writes the /me store; renders nothing
// when closed.

import { useEffect, useRef, useState } from "react";

import { deletePicture, updateMe, uploadPicture } from "../../api/users";
import { GAvatar, GButton, GFormField, GInput, GSwitch, GlyphSlot } from "../Goofy";
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
      className="rounded-[12px] border-2 border-ink object-cover"
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

export default function ProfilePanel() {
  const open = useProfilePanel((s) => s.open);
  const close = useProfilePanel((s) => s.closePanel);
  const me = useMe((s) => s.me);
  const setMe = useMe((s) => s.setMe);
  const load = useMe((s) => s.load);
  const signOut = useAuth((s) => s.signOut);

  const [fullName, setFullName] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    if (me) {
      setFullName(me.full_name ?? "");
      setStatus(me.status ?? "");
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
  const isAway = !!me?.is_away;

  async function save() {
    setSaving(true);
    setErr(null);
    setSaved(false);
    try {
      setMe(await updateMe({ full_name: fullName.trim(), status }));
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save your profile.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleAway(next: boolean) {
    if (!me) return;
    setMe({ ...me, is_away: next }); // optimistic
    try {
      setMe(await updateMe({ is_away: next }));
    } catch {
      setMe({ ...me, is_away: !next }); // revert
    }
  }

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setErr(null);
    try {
      setMe(await uploadPicture(file));
    } catch {
      setErr("Picture upload failed — use a PNG/JPEG/WebP under 5 MB.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removePicture() {
    setUploading(true);
    setErr(null);
    try {
      setMe(await deletePicture());
    } catch {
      setErr("Could not remove the picture.");
    } finally {
      setUploading(false);
    }
  }

  const stickerCard = "border-2 border-ink rounded-[14px] shadow-ink-1 bg-bg-1";
  const linkBtn =
    "text-[12px] font-semibold underline-offset-2 hover:underline disabled:opacity-50";

  return (
    <div className="fixed inset-0 z-[60] flex justify-end" role="dialog" aria-modal="true">
      <div
        className="flex-1 bg-[oklch(0.26_0.03_285/0.30)]"
        onClick={close}
        aria-hidden
      />
      <aside className="w-[360px] max-w-[88vw] h-full bg-bg-2 paper-dots border-l-2 border-ink shadow-ink-3 flex flex-col">
        <header className="px-4 py-3 flex items-center gap-2 border-b-2 border-ink/15">
          <span className="font-display font-semibold text-[17px] text-text-0 flex-1 tracking-[-0.01em]">
            Profile
          </span>
          <button
            type="button"
            onClick={close}
            aria-label="Close"
            className="text-text-3 hover:text-text-0"
          >
            <GlyphSlot name="x" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3.5">
          {/* Identity sticker */}
          <div className={`${stickerCard} p-3 flex items-center gap-3`}>
            <UserAvatar
              pictureUrl={me?.picture_url}
              name={displayName}
              sizePx={52}
              isAway={isAway}
              showDot
            />
            <div className="min-w-0 flex-1">
              <div className="font-display font-semibold text-[15px] text-text-0 truncate">
                {displayName}
              </div>
              <div className="text-[11.5px] text-text-3 truncate">{me?.email}</div>
              <div className="flex gap-2.5 mt-1.5">
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                  className={`${linkBtn} text-ai`}
                >
                  {uploading ? "Uploading…" : me?.picture_url ? "Change" : "Add picture"}
                </button>
                {me?.picture_url ? (
                  <button
                    type="button"
                    onClick={removePicture}
                    disabled={uploading}
                    className={`${linkBtn} text-text-3 hover:text-danger`}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                className="hidden"
                onChange={onPickFile}
              />
            </div>
          </div>

          {/* Availability toggle */}
          <div className={`${stickerCard} p-3 flex items-center gap-2.5`}>
            <span
              className={
                "w-2.5 h-2.5 rounded-full shrink-0 " + (isAway ? "bg-text-4" : "bg-ok")
              }
            />
            <div className="flex-1 leading-tight">
              <div className="font-display font-semibold text-[13.5px] text-text-0">
                {isAway ? "Away" : "Active"}
              </div>
              <div className="text-[11px] text-text-3">
                {isAway ? "Shown as away to teammates" : "Shown as active"}
              </div>
            </div>
            <GSwitch on={!isAway} onChange={(next) => void toggleAway(!next)} aria-label="Active" />
          </div>

          <GFormField label="Display name">
            <GInput
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your name"
              icon={null}
            />
          </GFormField>

          <GFormField label="Status">
            <GInput
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              placeholder="What are you up to?"
              icon={null}
            />
          </GFormField>

          {err ? (
            <div role="alert" className="text-danger text-[12px] leading-[1.45]">
              {err}
            </div>
          ) : null}
          {saved ? <div className="text-ok text-[12px]">Saved.</div> : null}

          <GButton
            variant="ai"
            size="sm"
            onClick={save}
            disabled={saving}
            className="self-start"
          >
            {saving ? "Saving…" : "Save profile"}
          </GButton>
        </div>

        <footer className="px-4 py-3 border-t-2 border-ink/15">
          <GButton
            variant="default"
            size="sm"
            onClick={() => {
              close();
              signOut();
            }}
          >
            Sign out
          </GButton>
        </footer>
      </aside>
    </div>
  );
}
