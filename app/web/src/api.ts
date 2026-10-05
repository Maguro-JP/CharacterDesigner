// app/server（FastAPI）の返す形。サーバー側の Job.public() と demi.check() に合わせる

export type Case = {
  ja?: string;
  kind?: string;
  tags?: string;
  hair?: string;
  hair_color?: string;
  negative?: string;
  anatomy?: string[];
  background?: string;
  strength?: number;
  seed?: number;
};

export type PartCheck = { view: string; part: string; pixels: number; gone: number; ok: boolean };

export type JobState = "queued" | "underlay" | "drawing" | "done" | "failed";

export type Job = {
  id: string;
  case_name: string;
  strength: number;
  tries: number;
  state: JobState;
  try_index: number | null;
  passed: boolean | null;
  error: string | null;
  created: number;
  started: number | null;
  finished: number | null;
  results: { try: number; result: PartCheck[] }[];
  files: string[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    // サーバーは失敗の理由を detail に日本語で入れて返す
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? res.statusText));
  }
  return (await res.json()) as T;
}

export const api = {
  cases: () => call<Record<string, Case>>("/api/cases"),
  jobs: () => call<Job[]>("/api/jobs"),
  submit: (caseName: string, tries: number) =>
    call<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ case: caseName, tries }) }),
  fileUrl: (jobId: string, name: string) => `/api/jobs/${jobId}/files/${name}`,
};
