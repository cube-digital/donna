// Shown after sign-in but before a workspace is active.
//
// On mount we fetch the user's workspaces and populate the store. The
// view branches:
//   - has workspaces  → list of `<GListItem/>` cards + an inline create form
//   - empty list      → hide the picker, show only the create form (so
//                       new users go straight to onboarding rather than
//                       staring at an empty section)
//
// Picking a workspace calls `setActive(id)`; App.tsx re-evaluates the
// gate on the next render and swaps in `<AppShell/>`.
//
// Whole surface is rendered inside `<GoofyTheme paper>` + a single
// `<GCard/>` so the picker reads as a sticker-book page rather than
// generic SaaS chrome.

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError } from "../api/client";
import {
  acceptInvitation,
  createWorkspace,
  listMyInvitations,
  listWorkspaces,
  type MyInvitation,
} from "../api/workspaces";
import { useAuth } from "../state/auth";
import { useWorkspace } from "../state/workspace";
import type { Workspace } from "../types";
import {
  GAvatar,
  GButton,
  GCard,
  GFormField,
  GInput,
  GoofyTheme,
} from "../components/Goofy";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

function workspaceHue(id: string): number {
  // Deterministic crayon hue per workspace id so adjacent workspace
  // avatars don't all look identical. Bias toward the warm/cool poles
  // of the goofy palette (yellow/sun, coral, blue, mint) by sampling a
  // wide spread of degrees.
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
}

export default function WorkspacePicker() {
  const setWorkspaces = useWorkspace((s) => s.setWorkspaces);
  const setActive = useWorkspace((s) => s.setActive);
  const workspaces = useWorkspace((s) => s.workspaces);
  const setLoading = useWorkspace((s) => s.setLoading);
  const loading = useWorkspace((s) => s.loading);
  const signOut = useAuth((s) => s.signOut);

  const [bootstrapped, setBootstrapped] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugDirty, setSlugDirty] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Pending invitations addressed to this user — surfaced so a normally
  // signed-in invitee can join without re-opening the invite email.
  const [invites, setInvites] = useState<MyInvitation[]>([]);
  const [acceptingToken, setAcceptingToken] = useState<string | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);

  async function handleAcceptInvite(token: string) {
    setAcceptingToken(token);
    setAcceptError(null);
    try {
      const { workspace_id } = await acceptInvitation(token);
      // Refresh memberships, then drop into the joined workspace.
      const list = await listWorkspaces();
      setWorkspaces(list);
      setActive(workspace_id);
    } catch (err) {
      setAcceptError(
        err instanceof ApiError
          ? err.message
          : "Could not accept the invitation.",
      );
      setAcceptingToken(null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const [list, mine] = await Promise.all([
          listWorkspaces(),
          listMyInvitations().catch(() => [] as MyInvitation[]),
        ]);
        if (cancelled) return;
        setWorkspaces(list);
        setInvites(mine);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiError
            ? err.message
            : "Could not load workspaces.",
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
          setBootstrapped(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setLoading, setWorkspaces]);

  const liveSlug = useMemo(() => {
    if (slugDirty) return slug;
    return slugify(name);
  }, [name, slug, slugDirty]);

  const canSubmit = name.trim().length > 0 && liveSlug.length > 0 && !creating;

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setCreating(true);
    setCreateError(null);
    try {
      const ws = await createWorkspace({
        name: name.trim(),
        slug: liveSlug,
      });
      setWorkspaces([...workspaces, ws]);
      setActive(ws.id);
    } catch (err) {
      setCreateError(
        err instanceof ApiError
          ? err.message
          : "Could not create workspace. Try a different slug?",
      );
    } finally {
      setCreating(false);
    }
  }

  const showList = workspaces.length > 0;
  const showCreate = bootstrapped;

  return (
    <GoofyTheme paper className="min-h-screen grid place-items-center px-5 py-10 text-text-1">
      <div className="w-full max-w-[520px] flex flex-col gap-4">
        <header className="text-center">
          <h1 className="m-0 font-display font-semibold text-[30px] text-text-0 leading-none tracking-[-0.01em]">
            Pick a workspace
          </h1>
          <p className="font-hand font-bold text-[20px] text-ai-deep mt-2 mb-0 leading-none">
            your workspaces live as stickers on this page
          </p>
        </header>

        {invites.length > 0 ? (
          <GCard className="flex flex-col gap-3">
            <div>
              <div className="font-display font-semibold text-[16px] text-text-0">
                {invites.length === 1
                  ? "You've been invited"
                  : "You have invitations"}
              </div>
              <div className="text-[12.5px] text-text-2">
                Accept to join the workspace.
              </div>
            </div>
            {acceptError ? (
              <div className="text-danger text-[12.5px]">{acceptError}</div>
            ) : null}
            <div className="flex flex-col gap-1.5">
              {invites.map((inv) => (
                <div
                  key={inv.token}
                  className="flex items-center gap-3 w-full p-2.5 rounded-[11px] border-2 border-ink shadow-ink-1 bg-bg-1"
                >
                  <GAvatar
                    name={inv.workspace_name}
                    color={`oklch(0.78 0.15 ${workspaceHue(inv.token)})`}
                    size="md"
                  />
                  <span className="flex-1 min-w-0 flex flex-col leading-tight gap-0.5">
                    <span className="font-display font-semibold text-[14px] text-text-0 truncate">
                      {inv.workspace_name}
                    </span>
                    <span className="text-[11.5px] text-text-3 truncate">
                      invited by {inv.invited_by}
                    </span>
                  </span>
                  <GButton
                    variant="ai"
                    disabled={acceptingToken !== null}
                    onClick={() => handleAcceptInvite(inv.token)}
                  >
                    {acceptingToken === inv.token ? "Joining…" : "Accept"}
                  </GButton>
                </div>
              ))}
            </div>
          </GCard>
        ) : null}

        <GCard className="flex flex-col gap-4">
          {loading && !bootstrapped ? (
            <div className="text-text-3 text-[13px] py-3">
              Loading workspaces…
            </div>
          ) : null}

          {loadError ? (
            <div className="text-danger text-[12.5px] py-2 px-3 border-2 border-danger rounded-[9px]">
              {loadError}
            </div>
          ) : null}

          {showList ? (
            <div className="flex flex-col gap-1.5">
              {workspaces.map((w: Workspace) => (
                // Manual sticker row — `GListItem` truncates its children to
                // a single nowrap line which can't accommodate an avatar +
                // two-line label + trailing affordance. The classes below
                // mirror `GListItem`'s sticker chrome (rounded-[11px], ink
                // border, mini-wiggle on hover) so the visual family stays
                // consistent.
                <button
                  key={w.id}
                  type="button"
                  onClick={() => setActive(w.id)}
                  aria-label={`Open ${w.name}`}
                  className="flex items-center gap-3 w-full text-left p-2.5 rounded-[11px] border-2 border-ink shadow-ink-1 bg-bg-1 cursor-pointer transition-[transform,box-shadow,background] duration-[120ms] ease-spring hover:bg-bg-2 hover:-translate-y-px hover:shadow-ink-3 motion-safe:hover:animate-mini-wiggle outline-none focus-visible:ring-2 focus-visible:ring-ai focus-visible:ring-offset-1 focus-visible:ring-offset-bg-1"
                >
                  <GAvatar
                    name={w.name}
                    color={`oklch(0.78 0.15 ${workspaceHue(w.id)})`}
                    size="md"
                  />
                  <span className="flex-1 min-w-0 flex flex-col leading-tight gap-0.5">
                    <span className="font-display font-semibold text-[14px] text-text-0 truncate">
                      {w.name}
                    </span>
                    <span className="font-mono text-[11.5px] text-text-3 truncate">
                      {w.slug}
                    </span>
                  </span>
                  <span className="text-text-3 text-[12px] font-medium shrink-0">
                    Open →
                  </span>
                </button>
              ))}
            </div>
          ) : null}

          {showList && showCreate ? (
            <div className="flex items-center gap-2.5">
              <span className="flex-1 border-t-2 border-dashed border-ink/40" />
              <span className="font-hand font-bold text-[18px] text-text-2 leading-none">
                or make a new one
              </span>
              <span className="flex-1 border-t-2 border-dashed border-ink/40" />
            </div>
          ) : null}

          {showCreate ? (
            <form onSubmit={handleCreate} className="flex flex-col gap-3">
              {!showList ? (
                <div className="font-display font-semibold text-[14px] text-text-1">
                  Create your first workspace
                </div>
              ) : null}

              <GFormField label="Name">
                <GInput
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Acme Inc."
                  // autoFocus is fine here — single primary input on a
                  // desktop-only workspace-picker page (mobile layout
                  // not yet supported by the design).
                  autoFocus
                  autoComplete="organization"
                  icon={null}
                />
              </GFormField>

              <GFormField label="Slug" hint="lowercase, dashes for spaces">
                <GInput
                  type="text"
                  value={liveSlug}
                  onChange={(e) => {
                    setSlug(slugify(e.target.value));
                    setSlugDirty(true);
                  }}
                  placeholder="acme"
                  // Slug is a URL token — not a dictionary word, never
                  // remembered by password managers, no autocomplete.
                  autoComplete="off"
                  spellCheck={false}
                  icon={null}
                  className="font-mono"
                />
              </GFormField>

              {createError ? (
                <div className="text-danger text-[12.5px] leading-[1.45]">
                  {createError}
                </div>
              ) : null}

              <GButton
                type="submit"
                variant="ai"
                size="md"
                disabled={!canSubmit}
                className="self-start"
                iconRight="bolt"
              >
                {creating ? "Creating…" : "Create workspace"}
              </GButton>
            </form>
          ) : null}
        </GCard>

        <div className="text-center">
          <button
            type="button"
            onClick={() => signOut()}
            className="text-text-3 text-[12.5px] px-2 py-1 rounded-md cursor-pointer hover:bg-bg-2 hover:text-text-0"
          >
            Sign out
          </button>
        </div>
      </div>
    </GoofyTheme>
  );
}
