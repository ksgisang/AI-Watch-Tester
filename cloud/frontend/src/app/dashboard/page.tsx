"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import TestProgress from "@/components/TestProgress";
import ScenarioEditor from "@/components/ScenarioEditor";
import FileUpload from "@/components/FileUpload";
import {
  createTest, getTest, uploadDocument, fetchBilling, convertScenario, cancelTest,
  startScan, getScan, generateScanPlan, executeScanTests, connectScanWS,
  type TestItem, type BillingInfo, type ScanItem, type TestPlanCategory,
} from "@/lib/api";
import { translateApiError } from "@/lib/errorMessages";

type Phase = "idle" | "generating" | "review" | "executing" | "done";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const t = useTranslations("dashboard");
  const tc = useTranslations("common");
  const te = useTranslations("errors");
  const ts = useTranslations("smartScan");
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
  const [activeTab, setActiveTab] = useState<"auto" | "custom" | "scan">("auto");
  const [customPrompt, setCustomPrompt] = useState("");
  const [converting, setConverting] = useState(false);
  const [convertedYaml, setConvertedYaml] = useState("");
  const [convertedInfo, setConvertedInfo] = useState<{ count: number; steps: number } | null>(null);
  const [cancelling, setCancelling] = useState(false);
  // Smart Scan state
  const [scanPhase, setScanPhase] = useState<"idle" | "scanning" | "plan" | "ready" | "executing">("idle");
  const [activeScan, setActiveScan] = useState<ScanItem | null>(null);
  const [scanProgress, setScanProgress] = useState<{
    pages: number; max: number; links: number; forms: number; buttons: number;
    features: string[]; currentUrl: string;
  }>({ pages: 0, max: 5, links: 0, forms: 0, buttons: 0, features: [], currentUrl: "" });
  const [planCategories, setPlanCategories] = useState<TestPlanCategory[]>([]);
  const [selectedTests, setSelectedTests] = useState<Set<string>>(new Set());
  const [authData, setAuthData] = useState<Record<string, string>>({});
  const [testData, setTestData] = useState<Record<string, string>>({});
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set());
  const [planLoading, setPlanLoading] = useState(false);
  const [scanExecuting, setScanExecuting] = useState(false);
  const scanWsRef = useRef<WebSocket | null>(null);

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

  // -- Smart Scan handlers --
  // Track whether plan generation was already triggered to avoid double-calls
  const planTriggeredRef = useRef(false);

  const handleStartScan = async () => {
    setError("");
    setScanPhase("scanning");
    planTriggeredRef.current = false;
    setScanProgress({ pages: 0, max: 5, links: 0, forms: 0, buttons: 0, features: [], currentUrl: "" });
    setPlanCategories([]);
    setSelectedTests(new Set());
    setAuthData({});
    setTestData({});

    try {
      const scan = await startScan(url);
      setActiveScan(scan);

      const triggerPlan = (scanId: number) => {
        if (planTriggeredRef.current) return;
        planTriggeredRef.current = true;
        getScan(scanId).then((updated) => {
          setActiveScan(updated);
          setScanPhase("plan");
          handleGeneratePlan(updated.id);
        }).catch(() => {
          setScanPhase("plan");
        });
      };

      // Connect WebSocket for progress
      const ws = connectScanWS(scan.id, (data) => {
        const type = data.type as string;
        if (type === "page_scanned") {
          setScanProgress((prev) => ({
            ...prev,
            pages: (data.pages_scanned as number) || prev.pages,
            max: (data.max_pages as number) || prev.max,
            links: (data.links_found as number) || prev.links,
            forms: (data.forms_found as number) || prev.forms,
            buttons: (data.buttons_found as number) || prev.buttons,
            features: (data.features as string[]) || prev.features,
            currentUrl: (data.url as string) || prev.currentUrl,
          }));
        } else if (type === "feature_detected") {
          setScanProgress((prev) => ({
            ...prev,
            features: [...new Set([...prev.features, data.feature as string])],
          }));
        } else if (type === "scan_complete") {
          triggerPlan(scan.id);
        } else if (type === "scan_error") {
          setError(String(data.error || "Scan failed"));
          setScanPhase("idle");
        }
      });
      scanWsRef.current = ws;

      // Also poll for completion (WebSocket might disconnect)
      const pollInterval = setInterval(async () => {
        try {
          const updated = await getScan(scan.id);
          if (updated.status === "completed") {
            clearInterval(pollInterval);
            triggerPlan(scan.id);
          } else if (updated.status === "failed") {
            clearInterval(pollInterval);
            setActiveScan(updated);
            setError(updated.error_message || "Scan failed");
            setScanPhase("idle");
          }
        } catch {
          // ignore
        }
      }, 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to start scan";
      setError(translateApiError(msg, te));
      setScanPhase("idle");
    }
  };

  const handleGeneratePlan = async (scanId: number) => {
    setPlanLoading(true);
    try {
      const locale = (typeof window !== "undefined" && document.documentElement.lang) || "en";
      const lang = locale.startsWith("ko") ? "ko" : "en";
      const result = await generateScanPlan(scanId, lang as "ko" | "en");
      setPlanCategories(result.categories);

      // Auto-select tests marked as selected or in auto_selected categories
      const autoSelected = new Set<string>();
      const autoExpanded = new Set<string>();
      for (const cat of result.categories) {
        if (cat.auto_selected) {
          autoExpanded.add(cat.id);
          for (const test of cat.tests) {
            if (test.selected !== false) {
              autoSelected.add(test.id);
            }
          }
        }
      }
      setSelectedTests(autoSelected);
      setExpandedCats(autoExpanded);
      setScanPhase("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to generate plan";
      setError(translateApiError(msg, te));
      setScanPhase("plan");
    } finally {
      setPlanLoading(false);
    }
  };

  const handleToggleTest = (testId: string) => {
    setSelectedTests((prev) => {
      const next = new Set(prev);
      if (next.has(testId)) next.delete(testId);
      else next.add(testId);
      return next;
    });
  };

  const handleToggleCategory = (cat: TestPlanCategory) => {
    const allInCat = cat.tests.map((t) => t.id);
    const allSelected = allInCat.every((id) => selectedTests.has(id));
    setSelectedTests((prev) => {
      const next = new Set(prev);
      for (const id of allInCat) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  };

  const handleToggleExpand = (catId: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev);
      if (next.has(catId)) next.delete(catId);
      else next.add(catId);
      return next;
    });
  };

  const handleExecuteScan = async () => {
    if (!activeScan || selectedTests.size === 0) return;
    setError("");
    setScanExecuting(true);

    try {
      const result = await executeScanTests(
        activeScan.id,
        Array.from(selectedTests),
        authData,
        testData,
      );
      // Switch to test execution phase
      const test = await getTest(result.test_id);
      setActiveTest(test);
      setPhase("executing");
      setScanPhase("executing");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to execute";
      setError(translateApiError(msg, te));
    } finally {
      setScanExecuting(false);
    }
  };

  // Feature name mapping
  const featureLabels: Record<string, string> = {
    login_form: ts("featureLogin"),
    search: ts("featureSearch"),
    cart: ts("featureCart"),
    product_list: ts("featureProduct"),
    review_form: ts("featureReview"),
    comment_form: ts("featureComment"),
    board_write: ts("featureBoard"),
    file_upload: ts("featureUpload"),
    admin_panel: ts("featureAdmin"),
    newsletter: ts("featureNewsletter"),
    social_login: ts("featureSocial"),
    pagination: ts("featurePagination"),
    filter_sort: ts("featureFilter"),
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
          <button
            type="button"
            onClick={() => setActiveTab("scan")}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "scan"
                ? "border-b-2 border-teal-600 text-teal-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {ts("tab")}
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

        {/* Smart Scan tab */}
        {activeTab === "scan" && (
          <div className="space-y-4">
            {/* Idle — Start button */}
            {scanPhase === "idle" && (
              <button
                type="button"
                onClick={handleStartScan}
                disabled={!url || isBusy}
                className="w-full rounded-lg bg-teal-600 px-5 py-3 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
              >
                {ts("startScan")}
              </button>
            )}

            {/* Scanning progress */}
            {scanPhase === "scanning" && (
              <div className="rounded-lg border border-teal-200 bg-teal-50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-teal-800">{ts("scanning")}</span>
                </div>
                {/* Progress bar */}
                <div className="h-2 overflow-hidden rounded-full bg-teal-100">
                  <div
                    className="h-full rounded-full bg-teal-500 transition-all duration-300"
                    style={{ width: `${scanProgress.max > 0 ? Math.min(100, Math.round((scanProgress.pages / scanProgress.max) * 100)) : 0}%` }}
                  />
                </div>
                <p className="text-xs text-teal-600">
                  {ts("scanProgress", { current: scanProgress.pages, max: scanProgress.max })}
                  {scanProgress.currentUrl && (
                    <span className="ml-2 text-teal-500 truncate block">{scanProgress.currentUrl}</span>
                  )}
                </p>
                {/* Stats */}
                <div className="flex flex-wrap gap-3 text-xs text-teal-700">
                  <span>{scanProgress.links} {ts("links")}</span>
                  <span>{scanProgress.forms} {ts("forms")}</span>
                  <span>{scanProgress.buttons} {ts("buttons")}</span>
                </div>
                {/* Detected features */}
                {scanProgress.features.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {scanProgress.features.map((f) => (
                      <span key={f} className="rounded-full bg-teal-100 px-2 py-0.5 text-[10px] font-medium text-teal-700">
                        {featureLabels[f] || f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Plan loading */}
            {(scanPhase === "plan" && planLoading) && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-center">
                <div className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
                <p className="mt-2 text-sm text-blue-700">{ts("generatingPlan")}</p>
              </div>
            )}

            {/* Scan summary + Test plan */}
            {(scanPhase === "ready" || (scanPhase === "plan" && !planLoading)) && activeScan && (
              <div className="space-y-4">
                {/* Summary card */}
                {activeScan.summary && (
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-gray-800">{ts("scanComplete")}</span>
                      {activeScan.summary.broken_links > 0 && (
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                          {activeScan.summary.broken_links} {ts("brokenLinks")}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-3 text-xs text-gray-600">
                      <span>{activeScan.summary.total_pages} {ts("pages")}</span>
                      <span>{activeScan.summary.total_links} {ts("links")}</span>
                      <span>{activeScan.summary.total_forms} {ts("forms")}</span>
                      <span>{activeScan.summary.total_buttons} {ts("buttons")}</span>
                    </div>
                    {/* Detected features */}
                    {activeScan.detected_features.length > 0 ? (
                      <div className="pt-1">
                        <p className="mb-1 text-[10px] font-medium text-gray-500 uppercase">{ts("detectedFeatures")}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {activeScan.detected_features.map((f) => (
                            <span key={f} className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700">
                              {featureLabels[f] || f}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-gray-400">{ts("noFeatures")}</p>
                    )}
                    {/* Free tier notice */}
                    {billing?.tier === "free" && (
                      <p className="text-[10px] text-amber-600">{ts("upgradeForMore")}</p>
                    )}
                  </div>
                )}

                {/* Test plan categories */}
                {planCategories.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold text-gray-800">{ts("testPlan")}</h3>

                    {planCategories.map((cat) => {
                      const catTests = cat.tests || [];
                      const catSelectedCount = catTests.filter((t) => selectedTests.has(t.id)).length;
                      const allInCatSelected = catSelectedCount === catTests.length && catTests.length > 0;
                      const isExpanded = expandedCats.has(cat.id);

                      return (
                        <div key={cat.id} className="rounded-lg border border-gray-200 overflow-hidden">
                          {/* Category header */}
                          <button
                            type="button"
                            onClick={() => handleToggleExpand(cat.id)}
                            className="flex w-full items-center justify-between bg-gray-50 px-4 py-2.5 text-left hover:bg-gray-100"
                          >
                            <div className="flex items-center gap-2">
                              <span className="text-sm">{isExpanded ? "▼" : "▶"}</span>
                              <span className="text-sm font-medium text-gray-800">{cat.name}</span>
                              {catSelectedCount > 0 && (
                                <span className="rounded-full bg-teal-100 px-1.5 py-0.5 text-[10px] font-medium text-teal-700">
                                  {catSelectedCount}
                                </span>
                              )}
                            </div>
                            <label className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={allInCatSelected}
                                onChange={() => handleToggleCategory(cat)}
                                className="h-3.5 w-3.5 rounded border-gray-300 text-teal-600"
                              />
                              <span className="text-[10px] text-gray-500">{ts("selectAll")}</span>
                            </label>
                          </button>

                          {/* Category tests */}
                          {isExpanded && (
                            <div className="divide-y divide-gray-100">
                              {catTests.map((test) => {
                                const isSelected = selectedTests.has(test.id);
                                return (
                                  <div key={test.id} className="px-4 py-2.5 space-y-1.5">
                                    <div className="flex items-start gap-2">
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleToggleTest(test.id)}
                                        className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 text-teal-600"
                                      />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                          <span className="text-sm font-medium text-gray-800">{test.name}</span>
                                          <span className={`rounded px-1 py-0.5 text-[9px] font-medium ${
                                            test.priority === "high"
                                              ? "bg-red-50 text-red-600"
                                              : test.priority === "medium"
                                              ? "bg-orange-50 text-orange-600"
                                              : "bg-gray-100 text-gray-500"
                                          }`}>
                                            {test.priority === "high" ? ts("priorityHigh") : test.priority === "medium" ? ts("priorityMedium") : ts("priorityLow")}
                                          </span>
                                          <span className="text-[10px] text-gray-400">~{test.estimated_time}s</span>
                                        </div>
                                        <p className="text-xs text-gray-500 mt-0.5">{test.description}</p>
                                        {test.requires_auth && (
                                          <span className="mt-0.5 inline-block rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">
                                            {ts("requiresLogin")}
                                          </span>
                                        )}
                                      </div>
                                    </div>

                                    {/* Auth fields — show when selected & requires_auth */}
                                    {isSelected && test.requires_auth && test.auth_fields && (
                                      <div className="ml-6 space-y-1.5 rounded-lg border border-amber-100 bg-amber-50/50 p-2">
                                        {test.auth_fields.map((field) => (
                                          <div key={field.key} className="flex items-center gap-2">
                                            <label className="w-20 text-[10px] font-medium text-gray-600">{field.label}</label>
                                            <input
                                              type={field.type === "password" ? "password" : "text"}
                                              value={authData[field.key] || ""}
                                              onChange={(e) => setAuthData((prev) => ({ ...prev, [field.key]: e.target.value }))}
                                              className="flex-1 rounded border border-gray-200 px-2 py-1 text-xs focus:border-teal-500 focus:outline-none"
                                              placeholder={field.required ? "" : ts("optional")}
                                            />
                                          </div>
                                        ))}
                                      </div>
                                    )}

                                    {/* Test data fields */}
                                    {isSelected && test.test_data_fields && test.test_data_fields.length > 0 && (
                                      <div className="ml-6 space-y-1.5 rounded-lg border border-gray-100 bg-gray-50 p-2">
                                        {test.test_data_fields.map((field) => (
                                          <div key={field.key} className="flex items-center gap-2">
                                            <label className="w-20 text-[10px] font-medium text-gray-600">{field.label}</label>
                                            <input
                                              type="text"
                                              value={testData[field.key] || ""}
                                              onChange={(e) => setTestData((prev) => ({ ...prev, [field.key]: e.target.value }))}
                                              className="flex-1 rounded border border-gray-200 px-2 py-1 text-xs focus:border-teal-500 focus:outline-none"
                                              placeholder={field.placeholder || ts("optional")}
                                            />
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* Execute button */}
                    <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
                      <span className="text-sm text-gray-600">
                        {selectedTests.size} {ts("selectedTests")}
                      </span>
                      <button
                        type="button"
                        onClick={handleExecuteScan}
                        disabled={selectedTests.size === 0 || scanExecuting || isBusy}
                        className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                      >
                        {scanExecuting ? ts("executing") : ts("runSelected")}
                      </button>
                    </div>
                  </div>
                )}
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
