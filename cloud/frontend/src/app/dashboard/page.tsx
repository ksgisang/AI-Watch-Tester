"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import TestProgress from "@/components/TestProgress";
import ScenarioEditor from "@/components/ScenarioEditor";
import FileUpload from "@/components/FileUpload";
import { createTest, getTest, uploadDocument, fetchBilling, convertScenario, cancelTest, type TestItem, type BillingInfo } from "@/lib/api";
import { translateApiError } from "@/lib/errorMessages";

type Phase = "idle" | "generating" | "review" | "executing" | "done";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const t = useTranslations("dashboard");
  const tc = useTranslations("common");
  const te = useTranslations("errors");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [activeTest, setActiveTest] = useState<TestItem | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [testPassed, setTestPassed] = useState(false);
  const [scenarioYaml, setScenarioYaml] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const stagedFilesRef = useRef<File[]>([]);
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [activeTab, setActiveTab] = useState<"auto" | "custom">("auto");
  const [customPrompt, setCustomPrompt] = useState("");
  const [converting, setConverting] = useState(false);
  const [convertedYaml, setConvertedYaml] = useState("");
  const [convertedInfo, setConvertedInfo] = useState<{ count: number; steps: number } | null>(null);
  const [cancelling, setCancelling] = useState(false);

  // Redirect if not authenticated
  if (!authLoading && !user) {
    router.push("/login");
    return null;
  }

  // Fetch billing info
  useEffect(() => {
    if (user) {
      fetchBilling().then(setBilling).catch(() => {});
    }
  }, [user]);

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">{tc("loading")}</p>
      </div>
    );
  }

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    setActiveTest(null);
    setPhase("idle");
    setScenarioYaml("");

    try {
      // 1. Create test
      const test = await createTest(url, "review");

      // 2. Upload staged files (if any)
      for (const file of stagedFilesRef.current) {
        await uploadDocument(test.id, file);
      }

      // 3. Start generation phase
      setActiveTest(test);
      setPhase("generating");
      setShowUpload(false);
      stagedFilesRef.current = [];
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create test";
      setError(translateApiError(msg, te));
    } finally {
      setSubmitting(false);
    }
  };

  const handleQuickTest = async () => {
    setError("");
    setSubmitting(true);
    setActiveTest(null);
    setPhase("idle");
    setScenarioYaml("");

    try {
      const test = await createTest(url, "auto");
      setActiveTest(test);
      setPhase("executing");
      setShowUpload(false);
      stagedFilesRef.current = [];
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create test";
      setError(translateApiError(msg, te));
    } finally {
      setSubmitting(false);
    }
  };

  const handleConvert = async () => {
    setError("");
    setConverting(true);
    setConvertedYaml("");
    setConvertedInfo(null);

    try {
      const result = await convertScenario(url, customPrompt);
      setConvertedYaml(result.scenario_yaml);
      setConvertedInfo({ count: result.scenarios_count, steps: result.steps_total });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Conversion failed";
      setError(translateApiError(msg, te));
    } finally {
      setConverting(false);
    }
  };

  const handleRunConverted = async () => {
    setError("");
    setSubmitting(true);
    setActiveTest(null);
    setPhase("idle");
    setScenarioYaml("");

    try {
      // Create test with pre-built YAML → goes straight to QUEUED
      const test = await createTest(url, "auto", convertedYaml);
      setActiveTest(test);
      setPhase("executing");
      setConvertedYaml("");
      setConvertedInfo(null);
      setCustomPrompt("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to start test";
      setError(translateApiError(msg, te));
    } finally {
      setSubmitting(false);
    }
  };

  const handleScenariosReady = async (testId: number) => {
    try {
      const test = await getTest(testId);
      setActiveTest(test);
      setScenarioYaml(test.scenario_yaml || "");
      setPhase("review");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load scenarios";
      setError(translateApiError(msg, te));
    }
  };

  const handleApprove = () => {
    setPhase("executing");
  };

  const handleComplete = (passed: boolean) => {
    setPhase("done");
    setTestPassed(passed);
    if (activeTest) {
      setActiveTest({ ...activeTest, status: passed ? "done" : "failed" });
    }
  };

  const handleCancel = async () => {
    if (!activeTest || cancelling) return;
    setCancelling(true);
    try {
      await cancelTest(activeTest.id);
      setActiveTest({ ...activeTest, status: "failed" });
      setPhase("done");
      setTestPassed(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to cancel test";
      setError(translateApiError(msg, te));
    } finally {
      setCancelling(false);
    }
  };

  const isBusy = submitting || (phase !== "idle" && phase !== "done");

  const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|\/|$)/.test(url);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      {/* Cloud mode header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
            {t("cloudMode")}
          </span>
          {billing && (
            <span className={`rounded-full px-3 py-1 text-xs font-medium ${
              billing.tier === "team"
                ? "bg-purple-100 text-purple-700"
                : billing.tier === "pro"
                ? "bg-blue-100 text-blue-700"
                : "bg-gray-100 text-gray-600"
            }`}>
              {billing.tier.toUpperCase()}
            </span>
          )}
        </div>
      </div>
      <p className="mb-4 text-sm text-gray-500">
        {t("subtitle")}
      </p>
      {/* Usage bar */}
      {billing && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">
              {billing.usage.monthly_used}/{billing.usage.monthly_limit} tests this month
            </span>
            {billing.tier === "free" && (
              <a href="/pricing" className="text-xs font-medium text-blue-600 hover:underline">
                Upgrade
              </a>
            )}
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-gray-200">
            <div
              className={`h-full rounded-full transition-all ${
                billing.usage.monthly_used / billing.usage.monthly_limit >= 0.9
                  ? "bg-red-500"
                  : billing.usage.monthly_used / billing.usage.monthly_limit >= 0.7
                  ? "bg-yellow-500"
                  : "bg-blue-500"
              }`}
              style={{
                width: `${Math.min(100, Math.round((billing.usage.monthly_used / billing.usage.monthly_limit) * 100))}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* URL Input */}
      <div className="mb-6 space-y-3">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            placeholder={t("urlPlaceholder")}
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
          />
          {activeTab === "auto" && (
            <button
              type="button"
              onClick={() => setShowUpload((v) => !v)}
              disabled={isBusy}
              className={`whitespace-nowrap rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors ${
                showUpload || stagedFilesRef.current.length > 0
                  ? "border-blue-300 bg-blue-50 text-blue-700"
                  : "border-gray-300 text-gray-500 hover:bg-gray-50"
              } disabled:opacity-50`}
              title="Attach specification documents"
            >
              {stagedFilesRef.current.length > 0
                ? t("docsCount", { count: stagedFilesRef.current.length })
                : t("attach")}
            </button>
          )}
        </div>

        {/* Localhost warning */}
        {isLocalhost && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <strong>{t("localhostWarning")}</strong>{" "}
            {t("localhostHint", { command: "aat serve" })}{" "}
            <a href="https://github.com/ksgisang/AI-Watch-Tester#local-mode" target="_blank" rel="noopener noreferrer" className="font-medium text-amber-900 underline">
              {t("localhostGuide")}
            </a>
          </div>
        )}

        {/* Tabs */}
        <div className="flex border-b border-gray-200">
          <button
            type="button"
            onClick={() => setActiveTab("auto")}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "auto"
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t("tabAutoGenerate")}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("custom")}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "custom"
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t("tabCustom")}
          </button>
        </div>

        {/* Auto Generate tab */}
        {activeTab === "auto" && (
          <>
            {showUpload && (
              <FileUpload
                onFilesChanged={(files) => {
                  stagedFilesRef.current = files;
                }}
              />
            )}
            <form onSubmit={handleGenerate} className="flex gap-2">
              <button
                type="submit"
                disabled={isBusy || !url}
                className="whitespace-nowrap rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? t("creatingBtn") : t("generateBtn")}
              </button>
              <button
                type="button"
                onClick={handleQuickTest}
                disabled={isBusy || !url}
                className="whitespace-nowrap rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {t("quickTestBtn")}
              </button>
            </form>
          </>
        )}

        {/* Custom Scenario tab */}
        {activeTab === "custom" && (
          <div className="space-y-3">
            <textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder={t("customPlaceholder")}
              rows={4}
              className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 focus:outline-none resize-none"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleConvert}
                disabled={converting || !url || !customPrompt.trim() || isBusy}
                className="whitespace-nowrap rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {converting ? t("converting") : t("convertBtn")}
              </button>
              {convertedInfo && (
                <span className="text-sm text-gray-500">
                  {t("convertedPreview", { count: convertedInfo.count, steps: convertedInfo.steps })}
                </span>
              )}
            </div>

            {/* Converted YAML preview */}
            {convertedYaml && (
              <div className="space-y-3">
                <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <pre className="whitespace-pre-wrap text-xs text-gray-700">{convertedYaml}</pre>
                </div>
                <button
                  type="button"
                  onClick={handleRunConverted}
                  disabled={submitting || isBusy}
                  className="whitespace-nowrap rounded-lg bg-green-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {submitting ? t("creatingBtn") : t("runConverted")}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Active Test */}
      {activeTest && (
        <div className="mb-6">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm text-gray-600">
              Test #{activeTest.id} — {activeTest.target_url}
            </p>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                activeTest.status === "generating"
                  ? "bg-purple-100 text-purple-700"
                  : activeTest.status === "review"
                  ? "bg-indigo-100 text-indigo-700"
                  : activeTest.status === "queued"
                  ? "bg-yellow-100 text-yellow-700"
                  : activeTest.status === "running"
                  ? "bg-blue-100 text-blue-700"
                  : activeTest.status === "done"
                  ? "bg-green-100 text-green-700"
                  : "bg-red-100 text-red-700"
              }`}
            >
              {activeTest.status}
            </span>
          </div>

          {/* Phase: generating */}
          {phase === "generating" && (
            <>
              <TestProgress
                testId={activeTest.id}
                onComplete={handleComplete}
                onScenariosReady={handleScenariosReady}
              />
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelling}
                className="mt-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {cancelling ? t("cancelling") : t("cancelBtn")}
              </button>
            </>
          )}

          {/* Phase: review */}
          {phase === "review" && scenarioYaml && (
            <ScenarioEditor
              testId={activeTest.id}
              initialYaml={scenarioYaml}
              onApprove={handleApprove}
            />
          )}

          {/* Phase: executing */}
          {phase === "executing" && (
            <>
              <TestProgress
                testId={activeTest.id}
                onComplete={handleComplete}
              />
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelling}
                className="mt-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {cancelling ? t("cancelling") : t("cancelBtn")}
              </button>
            </>
          )}

          {/* Phase: done */}
          {phase === "done" && (
            <div className="mt-4 flex items-center gap-3">
              <span
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                  testPassed
                    ? "bg-green-100 text-green-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {testPassed ? t("passed") : t("failed")}
              </span>
              <button
                onClick={() => router.push(`/tests/${activeTest.id}`)}
                className="text-sm text-blue-600 hover:underline"
              >
                {t("viewDetails")}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Quick links */}
      <div className="space-y-3">
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <p className="text-sm text-gray-600">
            {t("historyIntro")}{" "}
            <button
              onClick={() => router.push("/tests")}
              className="text-blue-600 hover:underline"
            >
              {t("historyLink")}
            </button>
            .
          </p>
        </div>
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 text-center">
          <p className="text-xs text-gray-500">
            {t("localModeHint")}{" "}
            <a
              href="https://github.com/ksgisang/AI-Watch-Tester#local-mode"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-blue-600 hover:underline"
            >
              {t("tryLocalMode")}
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
