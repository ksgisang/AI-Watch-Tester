"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import TestProgress from "@/components/TestProgress";
import ScenarioEditor from "@/components/ScenarioEditor";
import FileUpload from "@/components/FileUpload";
import { createTest, getTest, uploadDocument, type TestItem } from "@/lib/api";

type Phase = "idle" | "generating" | "review" | "executing" | "done";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const t = useTranslations("dashboard");
  const tc = useTranslations("common");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [activeTest, setActiveTest] = useState<TestItem | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [testPassed, setTestPassed] = useState(false);
  const [scenarioYaml, setScenarioYaml] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const stagedFilesRef = useRef<File[]>([]);

  // Redirect if not authenticated
  if (!authLoading && !user) {
    router.push("/login");
    return null;
  }

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
      setError(err instanceof Error ? err.message : "Failed to create test");
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
      setError(err instanceof Error ? err.message : "Failed to create test");
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
      setError(err instanceof Error ? err.message : "Failed to load scenarios");
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

  const isBusy = submitting || (phase !== "idle" && phase !== "done");

  const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|\/|$)/.test(url);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      {/* Cloud mode header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
          {t("cloudMode")}
        </span>
      </div>
      <p className="mb-6 text-sm text-gray-500">
        {t("subtitle")}
      </p>

      {/* URL Input + Attach + Action Buttons */}
      <form onSubmit={handleGenerate} className="mb-6 space-y-3">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            placeholder={t("urlPlaceholder")}
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
          />
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
        </div>

        {/* File staging area (expandable) */}
        {showUpload && (
          <FileUpload
            onFilesChanged={(files) => {
              stagedFilesRef.current = files;
            }}
          />
        )}

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

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={isBusy}
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
        </div>
      </form>

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
            <TestProgress
              testId={activeTest.id}
              onComplete={handleComplete}
              onScenariosReady={handleScenariosReady}
            />
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
            <TestProgress
              testId={activeTest.id}
              onComplete={handleComplete}
            />
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
