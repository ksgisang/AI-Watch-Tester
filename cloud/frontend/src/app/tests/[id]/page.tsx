"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import { getTest, API_URL, type TestItem } from "@/lib/api";

interface StepResult {
  step: number;
  action?: string;
  description?: string;
  target?: string;
  value?: string;
  status: string;
  error?: string;
  elapsed_ms?: number;
  screenshot_before?: string;
  screenshot_after?: string;
  screenshot_error?: string;
}

interface ScenarioResult {
  scenario_id: string;
  scenario_name: string;
  passed: boolean;
  steps: StepResult[];
}

interface ConsoleLogEntry {
  level: string; // "error" | "warning" | "info"
  text: string;
}

interface ResultJSON {
  passed: boolean;
  scenarios?: ScenarioResult[];
  error?: string;
  duration_ms?: number;
  screenshots_dir?: string;
  initial_screenshot?: string;
  console_logs?: ConsoleLogEntry[];
}

const STATUS_BADGE: Record<string, string> = {
  passed: "bg-green-100 text-green-700",
  done: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  error: "bg-red-100 text-red-700",
  queued: "bg-yellow-100 text-yellow-700",
  running: "bg-blue-100 text-blue-700",
};

function screenshotUrl(path: string | undefined | null): string | null {
  if (!path) return null;
  // Base64 data URLs are used directly (Render ephemeral FS)
  if (path.startsWith("data:image/")) return path;
  // Legacy: file path format → static file URL
  const relative = path.replace(/^(cloud\/)?screenshots\//, "");
  return `${API_URL}/screenshots/${relative}`;
}

/* ------------------------------------------------------------------ */
/* Screenshot Modal                                                     */
/* ------------------------------------------------------------------ */

function ScreenshotModal({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw]"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-white text-gray-600 shadow-lg hover:bg-gray-100"
        >
          &#10005;
        </button>
        <img
          src={src}
          alt={alt}
          className="max-h-[85vh] max-w-[85vw] rounded-lg object-contain shadow-2xl"
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Console Log Icon                                                     */
/* ------------------------------------------------------------------ */

function ConsoleIcon({ level }: { level: string }) {
  if (level === "error") {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-red-100 text-[10px] text-red-600">
        &#10007;
      </span>
    );
  }
  if (level === "warning") {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-orange-100 text-[10px] text-orange-600">
        &#9888;
      </span>
    );
  }
  return (
    <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-gray-100 text-[10px] text-gray-500">
      i
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Main Page                                                            */
/* ------------------------------------------------------------------ */

export default function TestDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const t = useTranslations("testDetail");
  const tc = useTranslations("common");
  const [test, setTest] = useState<TestItem | null>(null);
  const [result, setResult] = useState<ResultJSON | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showScenarios, setShowScenarios] = useState(false);
  const [modalImage, setModalImage] = useState<{ src: string; alt: string } | null>(null);
  const [showConsole, setShowConsole] = useState(false);

  const testId = Number(params.id);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (user && testId) fetchTest();
  }, [user, authLoading, testId]);

  const fetchTest = async () => {
    try {
      const data = await getTest(testId);
      setTest(data);
      if (data.result_json) {
        setResult(JSON.parse(data.result_json));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load test");
    } finally {
      setLoading(false);
    }
  };

  const openModal = useCallback((src: string, alt: string) => {
    setModalImage({ src, alt });
  }, []);

  const closeModal = useCallback(() => {
    setModalImage(null);
  }, []);

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">{tc("loading")}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  if (!test) return null;

  const consoleLogs = result?.console_logs ?? [];
  const errorCount = consoleLogs.filter((l) => l.level === "error").length;
  const warnCount = consoleLogs.filter((l) => l.level === "warning").length;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* Screenshot modal */}
      {modalImage && (
        <ScreenshotModal src={modalImage.src} alt={modalImage.alt} onClose={closeModal} />
      )}

      {/* Header */}
      <button
        onClick={() => router.push("/tests")}
        className="mb-4 text-sm text-gray-500 hover:text-gray-700"
      >
        &larr; {t("backToHistory")}
      </button>

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">
            {t("testTitle", { id: test.id })}
          </h1>
          <p className="mt-1 text-sm text-gray-600">{test.target_url}</p>
          <p className="mt-0.5 text-xs text-gray-400">
            {new Date(test.created_at).toLocaleString()}
            {result?.duration_ms &&
              ` · ${(result.duration_ms / 1000).toFixed(1)}s`}
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-sm font-medium ${
            STATUS_BADGE[test.status] || "bg-gray-100 text-gray-600"
          }`}
        >
          {test.status}
        </span>
      </div>

      {/* Error message */}
      {test.error_message && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {test.error_message}
        </div>
      )}

      {/* Progress summary */}
      {test.steps_total > 0 && (
        <div className="mb-6 rounded-lg border border-gray-200 p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-gray-600">{t("progress")}</span>
            <span className="text-gray-900">
              {t("stepsCount", { completed: test.steps_completed, total: test.steps_total })}
            </span>
          </div>
          <div className="h-2 rounded-full bg-gray-100">
            <div
              className={`h-2 rounded-full ${
                test.status === "done" ? "bg-green-500" : test.status === "failed" ? "bg-red-400" : "bg-blue-500"
              }`}
              style={{
                width: `${
                  test.steps_total > 0
                    ? (test.steps_completed / test.steps_total) * 100
                    : 0
                }%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Scenario YAML viewer (collapsible) */}
      {test.scenario_yaml && (
        <div className="mb-6 rounded-lg border border-gray-200">
          <button
            onClick={() => setShowScenarios(!showScenarios)}
            className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
          >
            <span className="text-sm font-medium text-gray-900">
              {t("viewScenarios")}
            </span>
            <svg
              className={`h-4 w-4 text-gray-500 transition-transform ${showScenarios ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {showScenarios && (
            <ScenarioViewer yaml={test.scenario_yaml} t={t} />
          )}
        </div>
      )}

      {/* Scenarios */}
      {result?.scenarios?.map((scenario, si) => (
        <div key={si} className="mb-6 rounded-lg border border-gray-200">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <h2 className="text-sm font-medium text-gray-900">
              {scenario.scenario_name || scenario.scenario_id}
            </h2>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                scenario.passed
                  ? "bg-green-100 text-green-700"
                  : "bg-red-100 text-red-700"
              }`}
            >
              {scenario.passed ? t("passed") : t("failed")}
            </span>
          </div>

          <div className="divide-y divide-gray-50">
            {scenario.steps.map((step, i) => (
              <div key={i} className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                      step.status === "passed"
                        ? "bg-green-100 text-green-600"
                        : step.status === "error" || step.status === "failed"
                        ? "bg-red-100 text-red-600"
                        : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {step.step}
                  </span>
                  <span className="text-sm text-gray-700">
                    {step.action || t("stepLabel", { step: step.step })}
                  </span>
                  {(step.target || step.value || step.description) && (
                    <span className="truncate text-xs text-gray-400" title={step.description || undefined}>
                      {step.target
                        ? `"${step.target}"`
                        : step.value
                          ? step.value
                          : step.description}
                    </span>
                  )}
                  <span
                    className={`ml-auto text-xs ${
                      step.status === "passed"
                        ? "text-green-600"
                        : "text-red-600"
                    }`}
                  >
                    {step.status}
                  </span>
                  {step.elapsed_ms !== undefined && (
                    <span className="text-xs text-gray-400">
                      {(step.elapsed_ms / 1000).toFixed(1)}s
                    </span>
                  )}
                </div>

                {/* Error detail — red box */}
                {step.error && (
                  <div className="mt-2 ml-7 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                    <span className="text-[10px] font-semibold text-red-500">{t("failureReason")}</span>
                    <p className="mt-0.5 text-xs text-red-700 font-mono whitespace-pre-wrap break-all">
                      {step.error}
                    </p>
                  </div>
                )}

                {/* Screenshots — click to enlarge */}
                {(step.screenshot_before ||
                  step.screenshot_after ||
                  step.screenshot_error) && (
                  <div className="mt-2 ml-7 flex gap-2">
                    {step.screenshot_before && (
                      <div className="text-center">
                        <img
                          src={screenshotUrl(step.screenshot_before) || ""}
                          alt="Before"
                          className="h-24 cursor-pointer rounded border border-gray-200 object-cover transition-transform hover:scale-105"
                          loading="lazy"
                          onClick={() =>
                            openModal(
                              screenshotUrl(step.screenshot_before) || "",
                              `Step ${step.step} — Before`
                            )
                          }
                        />
                        <span className="text-[10px] text-gray-400">
                          {t("before")}
                        </span>
                      </div>
                    )}
                    {step.screenshot_after && (
                      <div className="text-center">
                        <img
                          src={screenshotUrl(step.screenshot_after) || ""}
                          alt="After"
                          className="h-24 cursor-pointer rounded border border-gray-200 object-cover transition-transform hover:scale-105"
                          loading="lazy"
                          onClick={() =>
                            openModal(
                              screenshotUrl(step.screenshot_after) || "",
                              `Step ${step.step} — After`
                            )
                          }
                        />
                        <span className="text-[10px] text-gray-400">
                          {t("after")}
                        </span>
                      </div>
                    )}
                    {step.screenshot_error && (
                      <div className="text-center">
                        <img
                          src={screenshotUrl(step.screenshot_error) || ""}
                          alt="Error"
                          className="h-24 cursor-pointer rounded border border-red-200 object-cover transition-transform hover:scale-105"
                          loading="lazy"
                          onClick={() =>
                            openModal(
                              screenshotUrl(step.screenshot_error) || "",
                              `Step ${step.step} — Error`
                            )
                          }
                        />
                        <span className="text-[10px] text-red-400">{t("error")}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* Console Errors */}
      {consoleLogs.length > 0 && (
        <div className="mb-6 rounded-lg border border-gray-200">
          <button
            onClick={() => setShowConsole(!showConsole)}
            className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-900">{t("consoleErrors")}</span>
              {errorCount > 0 && (
                <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-600">
                  {errorCount}
                </span>
              )}
              {warnCount > 0 && (
                <span className="rounded-full bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-600">
                  {warnCount}
                </span>
              )}
            </div>
            <svg
              className={`h-4 w-4 text-gray-500 transition-transform ${showConsole ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {showConsole && (
            <div className="border-t border-gray-100 max-h-64 overflow-y-auto">
              {consoleLogs.map((log, i) => (
                <div
                  key={i}
                  className={`flex items-start gap-2 px-4 py-1.5 text-xs ${
                    log.level === "error"
                      ? "bg-red-50"
                      : log.level === "warning"
                      ? "bg-orange-50"
                      : "bg-white"
                  }`}
                >
                  <ConsoleIcon level={log.level} />
                  <span
                    className={`font-mono break-all ${
                      log.level === "error"
                        ? "text-red-700"
                        : log.level === "warning"
                        ? "text-orange-700"
                        : "text-gray-600"
                    }`}
                  >
                    {log.text}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Raw result fallback */}
      {result && !result.scenarios && result.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {result.error}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Scenario YAML Viewer                                                */
/* ------------------------------------------------------------------ */

interface ParsedStep {
  step?: number;
  action?: string;
  description?: string;
  target?: { text?: string };
  value?: string;
  assert_type?: string;
  expected?: Array<{ type?: string; value?: string }>;
  humanize?: boolean;
}

interface ParsedScenario {
  id?: string;
  name?: string;
  description?: string;
  tags?: string[];
  steps?: ParsedStep[];
  expected_result?: Array<{ type?: string; value?: string }>;
}

const ACTION_COLORS: Record<string, string> = {
  navigate: "bg-blue-100 text-blue-700",
  find_and_click: "bg-purple-100 text-purple-700",
  find_and_type: "bg-amber-100 text-amber-700",
  type_text: "bg-amber-100 text-amber-700",
  press_key: "bg-gray-100 text-gray-700",
  assert: "bg-green-100 text-green-700",
  wait: "bg-gray-100 text-gray-500",
  screenshot: "bg-cyan-100 text-cyan-700",
};

function ScenarioViewer({
  yaml: yamlStr,
  t,
}: {
  yaml: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
}) {
  let scenarios: ParsedScenario[] = [];
  try {
    // scenario_yaml can be a list or {scenarios: [...]}
    const parsed = JSON.parse(
      JSON.stringify(
        // simple YAML-like parse: split documents
        yamlStr
      )
    );
    // Actually we need to parse YAML — but we don't have js-yaml in frontend.
    // scenario_yaml is stored as YAML string. Let's parse it manually for common patterns.
    // Better approach: parse in a simple way since the YAML is machine-generated.
    scenarios = parseSimpleYaml(yamlStr);
  } catch {
    // fallback: show raw
  }

  if (scenarios.length === 0) {
    return (
      <div className="border-t border-gray-100 px-4 py-3">
        <pre className="max-h-80 overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-700 whitespace-pre-wrap">
          {yamlStr}
        </pre>
      </div>
    );
  }

  return (
    <div className="border-t border-gray-100 divide-y divide-gray-50">
      {scenarios.map((sc, si) => (
        <div key={si} className="px-4 py-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-mono text-gray-600">
              {sc.id || `SC-${si + 1}`}
            </span>
            <span className="text-sm font-medium text-gray-900">
              {sc.name || t("scenarioLabel")}
            </span>
          </div>
          {sc.description && (
            <p className="mb-2 text-xs text-gray-500">{sc.description}</p>
          )}
          {sc.tags && sc.tags.length > 0 && (
            <div className="mb-2 flex gap-1">
              {sc.tags.map((tag, ti) => (
                <span key={ti} className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-600">
                  {tag}
                </span>
              ))}
            </div>
          )}
          <div className="space-y-1">
            {sc.steps?.map((step, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-gray-100 text-[10px] text-gray-500">
                  {step.step ?? i + 1}
                </span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${ACTION_COLORS[step.action || ""] || "bg-gray-100 text-gray-600"}`}>
                  {step.action || "?"}
                </span>
                <span className="text-gray-700">
                  {step.description || ""}
                </span>
                {step.target?.text && (
                  <span className="shrink-0 rounded bg-gray-50 px-1 text-[10px] text-gray-500 font-mono">
                    target: &quot;{step.target.text}&quot;
                  </span>
                )}
                {step.value && step.action !== "navigate" && (
                  <span className="shrink-0 rounded bg-gray-50 px-1 text-[10px] text-gray-500 font-mono">
                    value: &quot;{step.value}&quot;
                  </span>
                )}
              </div>
            ))}
          </div>
          {sc.expected_result && sc.expected_result.length > 0 && (
            <div className="mt-2 rounded bg-green-50 px-2 py-1">
              <span className="text-[10px] font-medium text-green-700">{t("expectedResult")}:</span>
              {sc.expected_result.map((er, ei) => (
                <span key={ei} className="ml-1 text-[10px] text-green-600">
                  {er.type}: &quot;{er.value}&quot;
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Simple YAML parser for machine-generated scenario YAML.
 * Handles the specific format used by AAT scenario generation.
 */
function parseSimpleYaml(yamlStr: string): ParsedScenario[] {
  try {
    // The YAML is a list of scenario objects. Try JSON first (some formats).
    const asJson = JSON.parse(yamlStr);
    if (Array.isArray(asJson)) return asJson;
    if (asJson?.scenarios) return asJson.scenarios;
  } catch {
    // Not JSON, parse as YAML manually using line-by-line
  }

  // Simple line-based YAML parser for known structure
  const scenarios: ParsedScenario[] = [];
  let current: ParsedScenario | null = null;
  let currentStep: ParsedStep | null = null;
  let inSteps = false;
  let inExpected = false;
  let inTags = false;

  for (const raw of yamlStr.split("\n")) {
    const line = raw.trimEnd();
    const trimmed = line.trimStart();
    const indent = line.length - trimmed.length;

    // New scenario (top-level list item)
    if (trimmed.startsWith("- id:")) {
      if (current) scenarios.push(current);
      current = { id: trimmed.replace("- id:", "").trim().replace(/['"]/g, ""), steps: [] };
      inSteps = false;
      inExpected = false;
      inTags = false;
      currentStep = null;
      continue;
    }

    if (!current) continue;

    // Scenario-level fields
    if (indent <= 2 && trimmed.startsWith("name:")) {
      current.name = trimmed.replace("name:", "").trim().replace(/['"]/g, "");
      inSteps = false; inExpected = false; inTags = false;
    } else if (indent <= 2 && trimmed.startsWith("description:")) {
      current.description = trimmed.replace("description:", "").trim().replace(/['"]/g, "");
      inSteps = false; inExpected = false; inTags = false;
    } else if (indent <= 2 && trimmed.startsWith("tags:")) {
      inTags = true; inSteps = false; inExpected = false;
      current.tags = [];
    } else if (indent <= 2 && trimmed.startsWith("steps:")) {
      inSteps = true; inTags = false; inExpected = false;
    } else if (indent <= 2 && trimmed.startsWith("expected_result:")) {
      inExpected = true; inSteps = false; inTags = false;
      current.expected_result = [];
    } else if (inTags && trimmed.startsWith("- ")) {
      current.tags = current.tags || [];
      current.tags.push(trimmed.replace("- ", "").replace(/['"]/g, ""));
    } else if (inExpected && trimmed.startsWith("- type:")) {
      // inline expected_result item
      current.expected_result = current.expected_result || [];
      const obj: { type?: string; value?: string } = {};
      obj.type = trimmed.replace("- type:", "").trim().replace(/['"]/g, "");
      current.expected_result.push(obj);
    } else if (inExpected && trimmed.startsWith("value:")) {
      const arr = current.expected_result || [];
      if (arr.length > 0) {
        arr[arr.length - 1].value = trimmed.replace("value:", "").trim().replace(/['"]/g, "");
      }
    } else if (inSteps && trimmed.startsWith("- step:")) {
      if (currentStep) current.steps!.push(currentStep);
      currentStep = { step: parseInt(trimmed.replace("- step:", "").trim()) };
    } else if (inSteps && currentStep) {
      if (trimmed.startsWith("action:")) {
        currentStep.action = trimmed.replace("action:", "").trim().replace(/['"]/g, "");
      } else if (trimmed.startsWith("description:")) {
        currentStep.description = trimmed.replace("description:", "").trim().replace(/['"]/g, "");
      } else if (trimmed.startsWith("value:")) {
        currentStep.value = trimmed.replace("value:", "").trim().replace(/['"]/g, "");
      } else if (trimmed.startsWith("humanize:")) {
        currentStep.humanize = trimmed.includes("true");
      } else if (trimmed.startsWith("target:")) {
        // target might be inline or multi-line
        currentStep.target = {};
      } else if (trimmed.startsWith("text:") && currentStep.target) {
        currentStep.target.text = trimmed.replace("text:", "").trim().replace(/['"]/g, "");
      } else if (trimmed.startsWith("assert_type:")) {
        currentStep.assert_type = trimmed.replace("assert_type:", "").trim().replace(/['"]/g, "");
      }
    }
  }

  // Push last items
  if (currentStep && current) current.steps!.push(currentStep);
  if (current) scenarios.push(current);

  return scenarios;
}
