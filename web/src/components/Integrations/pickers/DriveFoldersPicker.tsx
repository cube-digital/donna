// Drive folders — drive picker + single-level folder browser.
//
// Picker endpoints:
//   GET /integrations/drive/subscription/picker/drives
//     → { drives: [{ id, name }] }   (virtual "My Drive" entry returned first)
//   GET /integrations/drive/subscription/picker/browse?drive_id&parent&page_token
//     → { files: [{ id, name, mimeType, ... }], nextPageToken? }
//
// Stored shape (matches Drive config_schema `folders` items):
//   { id, name, recursive, drive_id? }[]

import { useEffect, useMemo, useState } from "react";

import { getPicker } from "../../../api/integrations";
import { Button } from "../../Ui/Button";
import { Field } from "../../Ui/Field";
import { Ic } from "../../Ui/Ic";
import { Select } from "../../Ui/Select";
import { Toggle } from "../../Ui/Toggle";
import type { PickerProps } from "./registry";

interface SelectedFolder {
  id: string;
  name: string;
  recursive: boolean;
  drive_id?: string | null;
}

interface DriveDTO {
  id: string;          // "my-drive" sentinel for the user's My Drive
  name: string;
}

interface FileDTO {
  id: string;
  name: string;
  mimeType?: string;
}

const FOLDER_MIME = "application/vnd.google-apps.folder";

export function DriveFoldersPicker(p: PickerProps) {
  const value = (Array.isArray(p.value) ? (p.value as SelectedFolder[]) : []) as SelectedFolder[];

  // Drives (top-level container picker)
  const [drives, setDrives] = useState<DriveDTO[]>([]);
  const [driveId, setDriveId] = useState<string>("");

  // Browse cache: drives + folder path → list of folders
  const [folders, setFolders] = useState<FileDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Load drives once
  useEffect(() => {
    let cancelled = false;
    getPicker("drive", "drives")
      .then((data) => {
        if (cancelled) return;
        const list = (data.drives as DriveDTO[] | undefined) ?? [];
        setDrives(list);
        if (list.length > 0) setDriveId(list[0].id);
      })
      .catch((e) => !cancelled && setErr(e?.message ?? "Failed to load drives"));
    return () => {
      cancelled = true;
    };
  }, []);

  // Browse current drive's root each time driveId changes
  useEffect(() => {
    if (!driveId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    const params: Record<string, string> = { drive_id: driveId };
    getPicker("drive", "browse", params)
      .then((data) => {
        if (cancelled) return;
        const files = (data.files as FileDTO[] | undefined) ?? [];
        // Show only folders.
        setFolders(files.filter((f) => f.mimeType === FOLDER_MIME));
      })
      .catch((e) => !cancelled && setErr(e?.message ?? "Failed to browse drive"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [driveId]);

  const selectedById = useMemo(() => {
    const m = new Map<string, SelectedFolder>();
    for (const f of value) m.set(f.id, f);
    return m;
  }, [value]);

  function toggleSelected(folder: FileDTO) {
    const id = folder.id;
    if (selectedById.has(id)) {
      p.onChange(value.filter((f) => f.id !== id));
    } else {
      const next: SelectedFolder = {
        id,
        name: folder.name,
        recursive: true,
        drive_id: driveId === "my-drive" ? null : driveId,
      };
      p.onChange([...value, next]);
    }
  }

  function setRecursive(id: string, recursive: boolean) {
    p.onChange(value.map((f) => (f.id === id ? { ...f, recursive } : f)));
  }

  function removeSelected(id: string) {
    p.onChange(value.filter((f) => f.id !== id));
  }

  return (
    <Field
      label={p.label}
      hint={err ?? p.hint ?? "Pick folders Donna should ingest from."}
    >
      <div className="flex flex-col gap-3">
        {/* Drive switcher */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-[0.04em] text-text-3">Drive</span>
          <Select
            value={driveId}
            onChange={(e) => setDriveId(e.target.value)}
            disabled={drives.length === 0}
          >
            {drives.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </div>

        {/* Folder browser */}
        <div className="border border-border-soft rounded-md bg-bg-2 max-h-[240px] overflow-y-auto">
          {loading ? (
            <div className="px-2.5 py-2 text-[12.5px] text-text-3">Loading…</div>
          ) : folders.length === 0 ? (
            <div className="px-2.5 py-2 text-[12.5px] text-text-3">No folders in this drive.</div>
          ) : (
            folders.map((f) => {
              const selected = selectedById.has(f.id);
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => toggleSelected(f)}
                  className="w-full flex items-center gap-2 px-2.5 py-1 text-left text-[13px] text-text-1 hover:bg-bg-3"
                >
                  <span
                    className={
                      "w-3 h-3 grid place-items-center rounded-sm border " +
                      (selected ? "bg-text-0 border-text-0" : "border-border-strong")
                    }
                  >
                    {selected && (
                      <svg width="8" height="8" viewBox="0 0 16 16" fill="none">
                        <path
                          d="M3 8.5l3 3 7-7"
                          stroke="var(--bg-0)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </span>
                  <Ic.folder />
                  <span className="flex-1 truncate text-text-0">{f.name}</span>
                </button>
              );
            })
          )}
        </div>

        {/* Selected summary */}
        {value.length > 0 && (
          <div className="flex flex-col gap-1">
            <div className="text-[10px] uppercase tracking-[0.04em] text-text-3 font-medium">
              Selected ({value.length})
            </div>
            <div className="flex flex-col gap-0.5">
              {value.map((f) => (
                <div
                  key={f.id}
                  className="flex items-center gap-2 px-2 py-1 bg-bg-2 border border-border-soft rounded-md"
                >
                  <Ic.folder />
                  <span className="flex-1 truncate text-[13px] text-text-0">{f.name}</span>
                  <span className="text-[11px] text-text-3">Recursive</span>
                  <Toggle
                    checked={f.recursive}
                    onChange={(v) => setRecursive(f.id, v)}
                    aria-label={`Recursive ${f.name}`}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => removeSelected(f.id)}
                    aria-label={`Remove ${f.name}`}
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Field>
  );
}
