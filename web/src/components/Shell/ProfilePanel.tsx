// Global profile panel — a right-side drawer opened from the WsRail avatar
// pill. Edit display name / handle / status, upload a profile picture, and
// sign out. Self-contained: reads/writes the /me store; renders nothing when
// closed.

import { useEffect, useRef, useState } from "react";

import { deletePicture, updateMe, uploadPicture } from "../../api/users";
import { GAvatar, GButton, GFormField, GInput, GlyphSlot } from "../Goofy";
import { useAuth } from "../../state/auth";
import { useMe } from "../../state/me";
import { useProfilePanel } from "../../state/profilePanel";

/** Picture when set, coloured initials otherwise. */
export function UserAvatar({
  pictureUrl,
  name,
  sizePx = 40,
}: {
  pictureUrl?: string | null;
  name?: string;
  sizePx?: number;
}) {
  if (pictureUrl) {
    return (
      <img
        src={pictureUrl}
        alt={name || "Profile picture"}
        className="rounded-[12px] border-2 border-ink object-cover shrink-0"
        style={{ width: sizePx, height: sizePx }}
      />
    );
  }
  const size = sizePx >= 48 ? "xl" : sizePx >= 40 ? "lg" : "md";
  return <GAvatar name={name || "?"} size={size} />;
}

export default function ProfilePanel() {
  const open = useProfilePanel((s) => s.open);
  const close = useProfilePanel((s) => s.closePanel);
  const me = useMe((s) => s.me);
  const setMe = useMe((s) => s.setMe);
  const load = useMe((s) => s.load);
  const signOut = useAuth((s) => s.signOut);

  const [fullName, setFullName] = useState("");
  const [handle, setHandle] = useState("");
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
      setHandle(me.handle ?? "");
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

  async function save() {
    setSaving(true);
    setErr(null);
    setSaved(false);
    try {
      const updated = await updateMe({
        full_name: fullName.trim(),
        handle: handle.trim() || null,
        status,
      });
      setMe(updated);
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save your profile.");
    } finally {
      setSaving(false);
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

  return (
    <div className="fixed inset-0 z-[60] flex justify-end" role="dialog" aria-modal="true">
      <div
        className="flex-1 bg-[oklch(0.26_0.03_285/0.30)]"
        onClick={close}
        aria-hidden
      />
      <aside className="w-[380px] max-w-[88vw] h-full bg-bg-1 border-l-2 border-ink shadow-ink-3 flex flex-col">
        <header className="px-4 py-3 flex items-center gap-2 border-b border-border-soft">
          <span className="font-display font-semibold text-[16px] text-text-0 flex-1">
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

        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
          {/* Picture + identity */}
          <div className="flex items-center gap-3">
            <UserAvatar pictureUrl={me?.picture_url} name={displayName} sizePx={56} />
            <div className="min-w-0 flex-1">
              <div className="font-display font-semibold text-[15px] text-text-0 truncate">
                {displayName}
              </div>
              <div className="text-[12px] text-text-3 truncate">{me?.email}</div>
              <div className="flex gap-2 mt-1.5">
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                  className="text-[12px] text-ai font-semibold underline-offset-2 hover:underline disabled:opacity-50"
                >
                  {uploading ? "Uploading…" : me?.picture_url ? "Change" : "Add picture"}
                </button>
                {me?.picture_url ? (
                  <button
                    type="button"
                    onClick={removePicture}
                    disabled={uploading}
                    className="text-[12px] text-text-3 hover:text-danger underline-offset-2 hover:underline disabled:opacity-50"
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

          <GFormField label="Display name">
            <GInput
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your name"
              icon={null}
            />
          </GFormField>

          <GFormField label="Handle">
            <GInput
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="handle"
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
            <div role="alert" className="text-danger text-[12.5px] leading-[1.45]">
              {err}
            </div>
          ) : null}
          {saved ? (
            <div className="text-ok text-[12.5px]">Saved.</div>
          ) : null}

          <GButton
            variant="ai"
            size="lg"
            onClick={save}
            disabled={saving}
            className="w-full justify-center"
          >
            {saving ? "Saving…" : "Save profile"}
          </GButton>
        </div>

        <footer className="px-4 py-3 border-t border-border-soft">
          <GButton
            variant="default"
            size="lg"
            onClick={() => {
              close();
              signOut();
            }}
            className="w-full justify-center"
          >
            Sign out
          </GButton>
        </footer>
      </aside>
    </div>
  );
}
