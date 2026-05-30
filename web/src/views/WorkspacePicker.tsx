// Shown after sign-in but before a workspace is active.
//
// On mount we fetch the user's workspaces and populate the store. The
// view branches:
//   - has workspaces  → show list of cards + an inline "Create" form
//   - empty list      → hide the picker, show only the create form (so
//                       new users go straight to onboarding rather than
//                       staring at an empty section)
//
// Picking a workspace calls `setActive(id)`; App.tsx re-evaluates the
// gate on the next render and swaps in <AppShell/>.

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError } from "../api/client";
import { createWorkspace, listWorkspaces } from "../api/workspaces";
import { useAuth } from "../state/auth";
import { useWorkspace } from "../state/workspace";
import type { Workspace } from "../types";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

function glyph(name: string): string {
  return (name?.trim()?.[0] ?? "?").toUpperCase();
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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const list = await listWorkspaces();
        if (cancelled) return;
        setWorkspaces(list);
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
  const showCreate = bootstrapped; // create form once we know the list is real

  return (
    <div className="min-h-screen bg-bg-0 text-text-1 grid place-items-center px-5 py-10">
      <div className="w-full max-w-[520px] bg-bg-1 border border-border-soft rounded-lg p-7 shadow-elevated">
        <h1 className="m-0 text-text-0 text-[22px] font-semibold tracking-[-0.01em]">
          Pick a workspace
        </h1>
        <p className="mt-1.5 mb-[18px] text-text-2 text-[13px] leading-[1.55]">
          Your workspaces show up here. Create one if you don&apos;t see anything.
        </p>

        {loading && !bootstrapped ? (
          <div className="text-text-3 text-[12px] py-3">
            Loading workspaces…
          </div>
        ) : null}

        {loadError ? (
          <div className="text-danger text-[12px] px-3 py-2.5 border border-danger rounded mb-3.5">
            {loadError}
          </div>
        ) : null}

        {showList ? (
          <div className="flex flex-col gap-1.5 mb-[22px]">
            {workspaces.map((w: Workspace) => (
              <button
                key={w.id}
                type="button"
                onClick={() => setActive(w.id)}
                className="flex items-center gap-3 px-3.5 py-3 bg-bg-2 border border-border-soft rounded text-left w-full cursor-pointer hover:bg-bg-3"
              >
                <span className="w-9 h-9 rounded-md bg-bg-3 text-text-0 grid place-items-center font-bold text-sm flex-shrink-0">
                  {glyph(w.name)}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium text-text-0">
                    {w.name}
                  </span>
                  <span className="block text-[11.5px] text-text-3 font-mono">
                    {w.slug}
                  </span>
                </span>
                <span className="text-text-3 text-[12px]">Open →</span>
              </button>
            ))}
          </div>
        ) : null}

        {showCreate ? (
          <form
            onSubmit={handleCreate}
            className={
              showList
                ? "flex flex-col gap-2.5 pt-2 mt-2 border-t border-border-soft"
                : "flex flex-col gap-2.5"
            }
          >
            <div
              className={`text-text-2 text-[11px] tracking-[0.04em] uppercase font-semibold${
                showList ? " mt-2" : ""
              }`}
            >
              {showList ? "Or create a new one" : "Create your first workspace"}
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-[11.5px] text-text-2">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Inc."
                autoFocus
                className="h-9 px-3 bg-bg-2 border border-border-strong rounded text-text-0 text-[13px]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11.5px] text-text-2">Slug</span>
              <input
                type="text"
                value={liveSlug}
                onChange={(e) => {
                  setSlug(slugify(e.target.value));
                  setSlugDirty(true);
                }}
                placeholder="acme"
                className="h-9 px-3 bg-bg-2 border border-border-strong rounded text-text-0 text-[13px] font-mono"
              />
            </label>

            {createError ? (
              <div className="text-danger text-[12px] py-1.5">
                {createError}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={!canSubmit}
              className={
                canSubmit
                  ? "mt-1 h-9 px-3.5 bg-text-0 text-bg-0 border border-text-0 rounded text-[13px] font-medium cursor-pointer"
                  : "mt-1 h-9 px-3.5 bg-bg-3 text-text-3 border border-border-soft rounded text-[13px] font-medium cursor-not-allowed"
              }
            >
              {creating ? "Creating…" : "Create workspace"}
            </button>
          </form>
        ) : null}

        <div className="mt-[22px] pt-3.5 border-t border-border-soft text-center">
          <button
            type="button"
            onClick={() => signOut()}
            className="text-text-3 text-[12px] px-2 py-1 rounded-sm cursor-pointer hover:bg-bg-2 hover:text-text-0"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
