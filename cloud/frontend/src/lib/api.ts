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
  mode: "review" | "auto" = "review",
  scenarioYaml?: string,
): Promise<TestItem> {
  const payload: Record<string, unknown> = { target_url: targetUrl, mode };
  if (scenarioYaml) payload.scenario_yaml = scenarioYaml;
  const res = await authFetch("/api/tests", {
    method: "POST",
    body: JSON.stringify(payload),
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

export async function cancelTest(testId: number): Promise<TestItem> {
  const res = await authFetch(`/api/tests/${testId}/cancel`, {
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

// -- Scenario Conversion --

export interface ValidationItem {
  scenario_idx: number;
  step: number;
  status: "verified" | "unverified";
  target_text: string;
  closest_match?: string | null;
}

export interface ValidationSummary {
  verified: number;
  total: number;
  percent: number;
}

export interface ConvertScenarioResult {
  scenario_yaml: string;
  scenarios_count: number;
  steps_total: number;
  validation: ValidationItem[];
  validation_summary: ValidationSummary | null;
}

export async function convertScenario(
  targetUrl: string,
  userPrompt: string,
  language: "ko" | "en" = "en"
): Promise<ConvertScenarioResult> {
  const res = await authFetch("/api/tests/convert", {
    method: "POST",
    body: JSON.stringify({
      target_url: targetUrl,
      user_prompt: userPrompt,
      language,
    }),
  });
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

// -- Smart Scan API --

export interface SiteType {
  type: string;
  confidence: number;
  indicators: string[];
}

export interface ScanSummary {
  total_pages: number;
  total_links: number;
  total_forms: number;
  total_buttons: number;
  total_nav_menus: number;
  broken_links: number;
  detected_features: string[];
  site_type?: SiteType;
}

export interface ScanItem {
  id: number;
  target_url: string;
  status: "scanning" | "completed" | "planning" | "planned" | "failed" | "cancelled";
  summary: ScanSummary | null;
  pages: Record<string, unknown>[] | null;
  broken_links: { url: string; status: number; error?: string }[] | null;
  detected_features: string[];
  logs: { phase: string; message: string; level?: string }[];
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export async function startScan(
  targetUrl: string,
  maxPages = 5,
  maxDepth = 3
): Promise<ScanItem> {
  const res = await authFetch("/api/scan", {
    method: "POST",
    body: JSON.stringify({ target_url: targetUrl, max_pages: maxPages, max_depth: maxDepth }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function getScan(scanId: number): Promise<ScanItem> {
  const res = await authFetch(`/api/scan/${scanId}`);
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export interface TestPlanCategory {
  id: string;
  name: string;
  auto_selected?: boolean;
  tests: TestPlanItem[];
}

export interface TestPlanItem {
  id: string;
  name: string;
  description: string;
  priority: "high" | "medium" | "low";
  estimated_time: number;
  requires_auth: boolean;
  selected: boolean;
  auth_fields?: { key: string; label: string; type: string; required: boolean }[];
  test_data_fields?: { key: string; label: string; placeholder?: string; required: boolean }[];
  actual_elements?: string[];
}

export interface ScanPlanResult {
  scan_id: number;
  categories: TestPlanCategory[];
}

export async function generateScanPlan(
  scanId: number,
  language: "ko" | "en" = "en"
): Promise<ScanPlanResult> {
  const res = await authFetch(`/api/scan/${scanId}/plan`, {
    method: "POST",
    body: JSON.stringify({ language }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export interface ExecuteScanResult {
  test_id: number;
  scenario_yaml: string;
  scenarios_count: number;
  steps_total: number;
  validation: ValidationItem[];
  validation_summary: ValidationSummary | null;
}

export async function executeScanTests(
  scanId: number,
  selectedTests: string[],
  authData: Record<string, string> = {},
  testData: Record<string, string> = {}
): Promise<ExecuteScanResult> {
  const res = await authFetch(`/api/scan/${scanId}/execute`, {
    method: "POST",
    body: JSON.stringify({
      selected_tests: selectedTests,
      auth_data: authData,
      test_data: testData,
    }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export function connectScanWS(
  scanId: number,
  onMessage: (data: Record<string, unknown>) => void,
  onClose?: () => void
): WebSocket {
  const wsUrl = API_URL.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsUrl}/api/scan/${scanId}/ws`);

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

// -- Health API (no auth required) --

export interface HealthCheck {
  status: string;
  error?: string;
  provider?: string;
  models_available?: number;
  key_configured?: boolean;
  active_tests?: number;
  max_concurrent?: number;
}

export interface HealthResponse {
  status: "healthy" | "degraded" | "down";
  checks: {
    database: HealthCheck;
    worker: HealthCheck;
    ai_provider: HealthCheck;
  };
  uptime_seconds: number;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/api/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

// -- API Keys --

export interface ApiKeyItem {
  id: number;
  prefix: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreatedItem {
  id: number;
  key: string;
  prefix: string;
  name: string;
  created_at: string;
}

export async function createApiKey(name: string): Promise<ApiKeyCreatedItem> {
  const res = await authFetch("/api/keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function listApiKeys(): Promise<ApiKeyItem[]> {
  const res = await authFetch("/api/keys");
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

export async function deleteApiKey(id: number): Promise<void> {
  const res = await authFetch(`/api/keys/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
}

// -- Billing --

export interface BillingUsage {
  monthly_used: number;
  monthly_limit: number;
  active_count: number;
  concurrent_limit: number;
}

export interface BillingInfo {
  tier: "free" | "pro" | "team";
  lemon_customer_id: string | null;
  lemon_subscription_id: string | null;
  plan_expires_at: string | null;
  usage: BillingUsage;
}

export async function fetchBilling(): Promise<BillingInfo> {
  const res = await authFetch("/api/billing/me");
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

export async function fetchBillingPortal(): Promise<{ url: string }> {
  const res = await authFetch("/api/billing/portal");
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

// -- Checkout URLs --

const CHECKOUT_URLS: Record<string, string> = {
  pro: process.env.NEXT_PUBLIC_LEMON_PRO_URL || "",
  team: process.env.NEXT_PUBLIC_LEMON_TEAM_URL || "",
};

export function getCheckoutUrl(plan: "pro" | "team", userId: string): string {
  const base = CHECKOUT_URLS[plan];
  if (!base) return "/pricing";
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}checkout[custom][user_id]=${encodeURIComponent(userId)}`;
}

// -- User Documents (reference docs) --

export interface DocumentItem {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  extracted_chars: number;
  created_at: string;
}

export interface DocumentListResponse {
  documents: DocumentItem[];
  count: number;
  max_allowed: number;
}

export async function listDocuments(): Promise<DocumentListResponse> {
  const res = await authFetch("/api/documents");
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

export async function uploadUserDocument(file: File): Promise<DocumentItem> {
  const token = await getToken();
  if (!token) throw new Error("Not authenticated");

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/api/documents/upload`, {
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

export async function deleteDocument(id: number): Promise<void> {
  const res = await authFetch(`/api/documents/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `Error ${res.status}`);
  }
}

export { API_URL };
