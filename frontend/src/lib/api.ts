import { authHeaders, getToken, handleUnauthorized } from "@/lib/token";

export type Level = "ok" | "review" | "empty";
export type FieldValue = string | string[] | null;

export const FIELD_NAMES = [
  "full_name",
  "id_number",
  "central_numbers",
  "receipt_date",
  "sender",
  "commitment_numbers",
] as const;
export type FieldName = (typeof FIELD_NAMES)[number];

export interface Reason {
  kind: string;
  code: string;
}

export interface FieldData {
  id: number;
  name: FieldName;
  value: FieldValue;
  level: Level;
  confidence: number;
  reasons: Reason[];
  manually_corrected: boolean;
  /** Normalized [x0, y0, x1, y1] of the value on the page image (fractions from the top-left). */
  box: [number, number, number, number] | null;
  box_verified?: boolean;
  /** What the model originally read (before any manual correction). */
  original: FieldValue;
}

export type Status = "pending" | "processing" | "done" | "failed";

export interface SourceFileData {
  id: number;
  filename: string;
  status: Status;
  progress: number;
  error: string | null;
  pages_total: number;
  pages_done: number;
  fields_total: number;
  fields_extracted: number;
  avg_confidence: number | null;
}

export interface FormData {
  id: number;
  source_file_id: number;
  filename: string;
  page_index: number;
  status: Status;
  error: string | null;
  workflow: Workflow | null;
  assigned_to: number | null;
  approver_comment: string | null;
  fields: Record<FieldName, FieldData | null>;
}

export interface BatchDetail {
  id: number;
  created_at: string;
  status: "processing" | "done";
  paused: boolean;
  files: SourceFileData[];
  forms: FormData[];
  counts: Record<Level, number>;
  failed_forms: number;
}

export interface BatchSummary {
  id: number;
  created_at: string;
  status: string;
  files: number;
  forms: number;
}

export type ExportFormat = "xlsx" | "csv" | "json";

export interface ExportOptions {
  format: ExportFormat;
  include_details: boolean;
  include_source_links: boolean;
  password_protect: boolean;
}

export interface ExportFile {
  filename: string;
  size_bytes: number;
  sheets: number;
  rows: number;
  fields: number;
  /** null when the file is password protected (its checksum changes on every save). */
  sha256: string | null;
}

/** One preview row: field values plus the review state of the form. */
export type ExportRow = Record<string, FieldValue | number | undefined> & {
  _form_id: number;
  _review: number;
  _confidence: number | null;
};

export interface ConfidenceRow {
  filename: string;
  page: number;
  fields: Record<string, { level: Level; confidence: number; manually_corrected: boolean }>;
}

export interface ExportSummary {
  review: number;
  failed_forms: number;
  forms: number;
  /** Only approved forms are exported. */
  approved: number;
  unapproved: number;
  processing: boolean;
  files: number;
  pages: number;
  pages_done: number;
  source_formats: string[];
  fields: Record<Level, number>;
  avg_confidence: number | null;
  readable_pct: number;
  scan_number: string;
  processing_seconds: number | null;
  sheet_name: string;
  columns: { field: FieldName; header: string }[];
  preview: ExportRow[];
  confidence_preview: ConfidenceRow[];
  options: ExportOptions;
  file: ExportFile;
  last_export: { created_at: string; filename: string; size_bytes: number; sha256: string } | null;
}

// ---------- users, workflow, dashboards ----------

export type Role = "intake" | "approver" | "lab_manager";
export type Workflow = "needs_fix" | "pending_approval" | "returned" | "approved";
export type BacklogState = "processing" | Workflow | "failed";
export type Stage = "processing" | "needs_fix" | "pending_approval" | "returned";
export type FlaggedFilter = "all" | "none" | "some" | "many";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
}

export interface QueueForm {
  id: number;
  batch_id: number;
  filename: string;
  page_index: number;
  workflow: Workflow;
  assigned_to: number | null;
  assigned_name: string | null;
  approver_comment: string | null;
  /** Fields not at level ok. */
  flagged: number;
  full_name: FieldValue;
  id_number: FieldValue;
  sender: FieldValue;
  waiting_since: string | null;
  changed_by: string | null;
}

export interface UploadRow {
  id: number;
  created_at: string;
  status: "processing" | "done";
  forms: number;
  done: number;
  failed: number;
}

export interface WorkloadRow extends User {
  in_queue: number | null;
  handled_week: number;
}

export type MyQueue =
  | {
      role: "intake";
      forms: QueueForm[];
      uploads: UploadRow[];
      today: { received: number; corrected: number; submitted: number; waiting: number };
    }
  | {
      role: "approver";
      forms: QueueForm[];
      history: { form_id: number; workflow: Workflow; at: string; comment: string | null }[];
      today: { approved: number; returned: number; waiting: number };
    }
  | { role: "lab_manager"; workload: WorkloadRow[] };

export interface DashAccuracy {
  accuracy: number | null;
  fields: number;
  approved_forms: number;
  by_day: { day: string; accuracy: number; fields: number }[];
}

export interface DashProblemFields {
  fields: { field: FieldName; corrections: number }[];
  senders: string[];
  cells: Record<FieldName, Record<string, number>>;
}

export interface DashTimeToApproval {
  avg_hours: number | null;
  forms: number;
  stages: { stage: Stage; avg_hours: number }[];
  by_day: ({ day: string; forms: number } & Record<Stage, number>)[];
}

/** The request never reached the server; the UI shows its own translated message. */
export class NetworkError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: { ...authHeaders(), ...init?.headers } });
  if (res.status === 401 && !url.startsWith("/api/auth/login")) handleUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listBatches: () => request<BatchSummary[]>("/api/batches"),
  getBatch: (id: number) => request<BatchDetail>(`/api/batches/${id}`),
  deleteBatch: (id: number) => request<{ ok: boolean }>(`/api/batches/${id}`, { method: "DELETE" }),
  exportSummary: (id: number) => request<ExportSummary>(`/api/batches/${id}/export/summary`),
  saveExportOptions: (id: number, options: ExportOptions) =>
    request<{ options: ExportOptions; file: ExportFile }>(`/api/batches/${id}/export/options`, {
      method: "PUT",
      ...json(options),
    }),
  /** Builds the file on the server (options are read from the DB) and returns it as a Blob. */
  async downloadExport(id: number, password?: string): Promise<Blob> {
    const body = json({ password: password || null, link_base: window.location.origin });
    const res = await fetch(`/api/batches/${id}/export`, {
      method: "POST",
      ...body,
      headers: { ...authHeaders(), ...body.headers },
    });
    if (res.status === 401) handleUnauthorized();
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new Error(detail);
    }
    return res.blob();
  },
  /** <img src> cannot send headers, so the token rides in the query string. */
  imageUrl: (formId: number) => `/api/forms/${formId}/image?token=${encodeURIComponent(getToken() ?? "")}`,
  retryForm: (formId: number) => request<{ ok: boolean }>(`/api/forms/${formId}/retry`, { method: "POST" }),
  updateField: (fieldId: number, value: FieldValue) =>
    request<FieldData>(`/api/fields/${fieldId}`, { method: "PATCH", ...json({ value }) }),
  approveField: (fieldId: number) => request<FieldData>(`/api/fields/${fieldId}/approve`, { method: "POST" }),
  resetField: (fieldId: number) => request<FieldData>(`/api/fields/${fieldId}/reset`, { method: "POST" }),
  pauseBatch: (id: number) => request<{ ok: boolean }>(`/api/batches/${id}/pause`, { method: "POST" }),
  resumeBatch: (id: number) => request<{ ok: boolean }>(`/api/batches/${id}/resume`, { method: "POST" }),
  cancelBatch: (id: number) => request<{ ok: boolean }>(`/api/batches/${id}/cancel`, { method: "POST" }),
  senders: () => request<string[]>("/api/senders"),

  // Auth and approval workflow
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/login", { method: "POST", ...json({ username, password }) }),
  me: () => request<User>("/api/auth/me"),
  myQueue: (flagged?: FlaggedFilter) =>
    request<MyQueue>(`/api/queue/me${flagged && flagged !== "all" ? `?flagged=${flagged}` : ""}`),
  submitForm: (formId: number) =>
    request<{ ok: boolean; workflow: Workflow; flagged: number }>(`/api/forms/${formId}/submit`, { method: "POST" }),
  approveForm: (formId: number) =>
    request<{ ok: boolean; workflow: Workflow }>(`/api/forms/${formId}/approve`, { method: "POST" }),
  returnForm: (formId: number, comment: string) =>
    request<{ ok: boolean; workflow: Workflow }>(`/api/forms/${formId}/return`, {
      method: "POST",
      ...json({ comment }),
    }),
  approveBulk: (ids: number[]) =>
    request<{ approved: number[]; skipped: number[] }>("/api/forms/approve-bulk", { method: "POST", ...json({ ids }) }),
  finalizeBatch: (batchId: number) =>
    request<{ approved: number[]; skipped: number[] }>(`/api/batches/${batchId}/finalize`, { method: "POST" }),
  assignForm: (formId: number, userId: number) =>
    request<{ ok: boolean }>(`/api/forms/${formId}/assign`, { method: "POST", ...json({ user_id: userId }) }),
  users: () => request<User[]>("/api/users"),
  intakeForms: () => request<QueueForm[]>("/api/forms/queue"),
  dashBacklog: () => request<{ states: { state: BacklogState; count: number }[] }>("/api/dashboard/backlog"),
  dashAccuracy: () => request<DashAccuracy>("/api/dashboard/accuracy"),
  dashProblemFields: () => request<DashProblemFields>("/api/dashboard/problem-fields"),
  dashTimeToApproval: () => request<DashTimeToApproval>("/api/dashboard/time-to-approval"),
  dashWorkload: () => request<WorkloadRow[]>("/api/dashboard/workload"),

  /** Upload with byte-level progress (fetch has no upload progress). */
  uploadBatch(files: File[], onProgress: (fraction: number) => void): Promise<BatchDetail> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new window.FormData();
      files.forEach((f) => form.append("files", f));
      xhr.open("POST", "/api/batches");
      Object.entries(authHeaders()).forEach(([k, v]) => xhr.setRequestHeader(k, v));
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        if (xhr.status === 401) handleUnauthorized();
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else {
          let detail = xhr.statusText;
          try {
            detail = JSON.parse(xhr.responseText).detail ?? detail;
          } catch {
            /* not JSON */
          }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new NetworkError("Network error"));
      xhr.send(form);
    });
  },
};
