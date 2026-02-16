const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getToken(): Promise<string | null> {
  const { createClient } = await import("./supabase");
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

async function authFetch(path: string, options: RequestInit = {}) {
  const token = await getToken();
  if (!token) throw new Error("Not authenticated");

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });
  return res;
}

// -- Tests API --

export interface TestItem {
  id: number;
  user_id: string;
  target_url: string;
  status: "generating" | "review" | "queued" | "running" | "done" | "failed";
  result_json: string | null;
  scenario_yaml: string | null;
  doc_text: string | null;
  error_message: string | null;
  steps_total: number;
  steps_completed: number;
  created_at: string;
  updated_at: string;
}

export interface TestListResponse {
  tests: TestItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function createTest(
  targetUrl: string,
  mode: "review" | "auto" = "review"
): Promise<TestItem> {
  const res = await authFetch("/api/tests", {
    method: "POST",
    body: JSON.stringify({ target_url: targetUrl, mode }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function updateScenarios(
  testId: number,
  scenarioYaml: string
): Promise<TestItem> {
  const res = await authFetch(`/api/tests/${testId}/scenarios`, {
    method: "PUT",
    body: JSON.stringify({ scenario_yaml: scenarioYaml }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function approveTest(testId: number): Promise<TestItem> {
  const res = await authFetch(`/api/tests/${testId}/approve`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export interface UploadResult {
  filename: string;
  size: number;
  extracted_chars: number;
}

export async function uploadDocument(
  testId: number,
  file: File
): Promise<UploadResult> {
  const token = await getToken();
  if (!token) throw new Error("Not authenticated");

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/api/tests/${testId}/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function listTests(
  page = 1,
  pageSize = 20
): Promise<TestListResponse> {
  const res = await authFetch(
    `/api/tests?page=${page}&page_size=${pageSize}`
  );
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

export async function getTest(id: number): Promise<TestItem> {
  const res = await authFetch(`/api/tests/${id}`);
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

// -- WebSocket --

export function connectTestWS(
  testId: number,
  onMessage: (data: Record<string, unknown>) => void,
  onClose?: () => void
): WebSocket {
  const wsUrl = API_URL.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsUrl}/api/tests/${testId}/ws`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {
      // ignore
    }
  };

  ws.onclose = () => onClose?.();
  return ws;
}

export { API_URL };
