"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import { getTest, API_URL, type TestItem } from "@/lib/api";

interface StepResult {
  step: number;
  action?: string;
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

interface ResultJSON {
  passed: boolean;
  scenarios?: ScenarioResult[];
  error?: string;
  duration_ms?: number;
  screenshots_dir?: string;
  initial_screenshot?: string;
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
  // Handle both "cloud/screenshots/..." and "screenshots/..." formats
  const relative = path.replace(/^(cloud\/)?screenshots\//, "");
  return `${API_URL}/screenshots/${relative}`;
}

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

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
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
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
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
                      {step.elapsed_ms}ms
                    </span>
                  )}
                </div>

                {step.error && (
                  <p className="mt-1 ml-7 text-xs text-red-600">
                    {step.error}
                  </p>
                )}

                {/* Screenshots */}
                {(step.screenshot_before ||
                  step.screenshot_after ||
                  step.screenshot_error) && (
                  <div className="mt-2 ml-7 flex gap-2">
                    {step.screenshot_before && (
                      <div className="text-center">
                        <img
                          src={screenshotUrl(step.screenshot_before) || ""}
                          alt="Before"
                          className="h-24 rounded border border-gray-200 object-cover"
                          loading="lazy"
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
                          className="h-24 rounded border border-gray-200 object-cover"
                          loading="lazy"
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
                          className="h-24 rounded border border-red-200 object-cover"
                          loading="lazy"
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

      {/* Raw result fallback */}
      {result && !result.scenarios && result.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {result.error}
        </div>
      )}
    </div>
  );
}
