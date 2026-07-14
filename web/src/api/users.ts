import { apiFetch } from "./client";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  handle: string | null;
  status: string;
  picture_url: string | null;
}

/** The signed-in user's own profile. Identity-scoped (no workspace header). */
export async function getMe(): Promise<Me> {
  return apiFetch<Me>("/api/v1/users/me", { skipWorkspace: true });
}

export async function updateMe(
  patch: Partial<Pick<Me, "full_name" | "handle" | "status">>,
): Promise<Me> {
  return apiFetch<Me>("/api/v1/users/me", {
    method: "PATCH",
    body: patch,
    skipWorkspace: true,
  });
}

export async function uploadPicture(file: File): Promise<Me> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<Me>("/api/v1/users/me/picture", {
    method: "POST",
    body: form,
    skipWorkspace: true,
  });
}

export async function deletePicture(): Promise<Me> {
  return apiFetch<Me>("/api/v1/users/me/picture", {
    method: "DELETE",
    skipWorkspace: true,
  });
}
