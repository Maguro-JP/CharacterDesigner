// app/server（FastAPI）の返す形。サーバー側の Job.public() と demi.check() に合わせる

export type PartSlot = "ears" | "tail" | "wings" | "horns";

export type Parts = Partial<Record<PartSlot, string>> & { color?: Partial<Record<PartSlot, string>> };

export type Case = {
  ja?: string;
  kind?: string;
  parts?: Parts;
  tags?: string;
  hair?: string;
  hair_color?: string;
  negative?: string;
  anatomy?: string[];
  background?: string;
  strength?: number;
  seed?: number;
};

// 種の設定で選べるもの。サーバーが描く道具（demi.py）の定義から返す
export type PartChoices = {
  shapes: Record<PartSlot, string[]>;
  kinds: string[];
  anatomy: string[];
  view_ja: Record<string, string>;
  part_ja: Record<string, string>;
};

export type PartCheck = { view: string; part: string; pixels: number; gone: number; ok: boolean };

export type JobState = "queued" | "underlay" | "drawing" | "done" | "failed";

export type FreeSpec = { prompt: string; negative: string; ja: string; seed: number; count: number; width: number; height: number };

export type StudioEvent = { t: number; role: string; stage: string; msg: string; file?: string; prompt?: string; reasons?: string[] };

export type Outcome = { passed: string | null; files: string[]; prompt: string; negative: string; reason: string; critique: string[]; hidden?: string[] };

export type Memory = { text: string; prompt: string; negative: string; ok: boolean; liked?: boolean; seed: number; size: number[]; reason: string; t: number };

export type Proposal = { id: string; kind: "studio" | "demi"; title: string; why: string; who: string; request: Record<string, unknown> };

export type Role = { name: string; ja: string; temper: string; does: string; may: string[] };

export type LayoutNode =
  | { type: "panel"; panel: string }
  | { type: "split"; direction: "row" | "column"; sizes: number[]; children: LayoutNode[] }
  | { type: "tabs"; children: LayoutNode[] };

export type Layout = { id: string; name: string; root: LayoutNode; notes?: string[] };

export type StudioIn = { text: string; prompt: string; negative: string; seed: number; size: "portrait" | "landscape" | "square"; tries: number; direct: boolean };

export type Job = {
  id: string;
  kind?: "demi" | "free" | "studio";
  events?: StudioEvent[];
  outcome?: Outcome | null;
  free?: FreeSpec | null;
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
  // 亜人は回ごとの検品（result）、自由に描くは描けた絵の名前（file）
  results: { try: number; result?: PartCheck[]; file?: string }[];
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

export type Reader = "local" | "claude" | "words" | "tags" | "check" | null;

export type FreeDescribe = {
  allowed: boolean;
  reason: string;
  prompt: string;
  negative: string;
  tags: string[];
  summary: string;
  reader: Reader;
  notes: string[];
};

export type LlmLocal = { ok: boolean; url?: string; model?: string | null; models?: string[]; error?: string };

export type LlmStatus = {
  local: LlmLocal;
  claude: boolean;
  saved?: { url?: string; model?: string };
  default_url?: string;
};

export type FreeJobIn = { prompt: string; negative: string; ja: string; seed: number; count: number; size: "portrait" | "landscape" | "square" };

export const api = {
  cases: () => call<Record<string, Case>>("/api/cases"),
  parts: () => call<PartChoices>("/api/parts"),
  saveCase: (name: string, c: Case) => call<Case>(`/api/cases/${name}`, { method: "PUT", body: JSON.stringify(c) }),
  jobs: () => call<Job[]>("/api/jobs"),
  submit: (caseName: string, tries: number) =>
    call<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ case: caseName, tries }) }),
  saveSample: (jobId: string, overwrite: boolean) =>
    call<{ saved: string }>(`/api/jobs/${jobId}/save`, { method: "POST", body: JSON.stringify({ overwrite }) }),
  preview: (c: Case) => call<{ id: string; files: string[] }>("/api/preview", { method: "POST", body: JSON.stringify(c) }),
  previewUrl: (id: string, name: string) => `/api/previews/${id}/${name}`,
  describe: (text: string) =>
    call<{ name: string | null; case: Case | null; used: string[]; unused: string[]; notes: string[]; reader: Reader }>("/api/describe", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  fileUrl: (jobId: string, name: string) => `/api/jobs/${jobId}/files/${name}`,
  llm: () => call<LlmStatus>("/api/llm"),
  roles: () => call<Role[]>("/api/studio/roles"),
  memory: () => call<Memory[]>("/api/memory"),
  like: (jobId: string, file: string) => call<Memory>("/api/memory/like", { method: "POST", body: JSON.stringify({ job_id: jobId, file }) }),
  proposals: () => call<{ idle: boolean; items: Proposal[] }>("/api/proposals"),
  doProposal: (id: string) => call<Job>(`/api/proposals/${id}/do`, { method: "POST" }),
  dismissProposal: (id: string) => call<{ ok: boolean }>(`/api/proposals/${id}/dismiss`, { method: "POST" }),
  studioSubmit: (body: StudioIn) => call<Job>("/api/studio/jobs", { method: "POST", body: JSON.stringify(body) }),
  layout: () => call<Layout>("/api/layout"),
  saveLayout: (l: Layout) => call<Layout>("/api/layout", { method: "PUT", body: JSON.stringify(l) }),
  resetLayout: () => call<Layout>("/api/layout", { method: "DELETE" }),
  llmProbe: (url: string) => call<LlmLocal>("/api/llm/probe", { method: "POST", body: JSON.stringify({ url, model: "" }) }),
  llmSave: (url: string, model: string) => call<LlmStatus>("/api/llm", { method: "PUT", body: JSON.stringify({ url, model }) }),
  freeDescribe: (text: string) => call<FreeDescribe>("/api/free/describe", { method: "POST", body: JSON.stringify({ text }) }),
  freeSubmit: (body: FreeJobIn) => call<Job>("/api/free/jobs", { method: "POST", body: JSON.stringify(body) }),
};
