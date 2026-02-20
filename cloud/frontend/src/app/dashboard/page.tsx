"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import TestProgress from "@/components/TestProgress";
import ScenarioEditor from "@/components/ScenarioEditor";
import {
  createTest, getTest, fetchBilling, convertScenario, cancelTest,
  startScan, getScan, generateScanPlan, executeScanTests, connectScanWS,
  listDocuments, uploadUserDocument, deleteDocument,
  type TestItem, type BillingInfo, type ScanItem, type TestPlanCategory,
  type ValidationItem, type ValidationSummary, type DocumentItem,
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
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [directMode, setDirectMode] = useState(false);
  const [additionalPrompt, setAdditionalPrompt] = useState("");
  const [additionalConverting, setAdditionalConverting] = useState(false);
  const [additionalYaml, setAdditionalYaml] = useState("");
  const [additionalInfo, setAdditionalInfo] = useState<{ count: number; steps: number } | null>(null);
  const [additionalRelevance, setAdditionalRelevance] = useState<{
    valid: boolean; reason: string; feature_missing: boolean; warnings: string[];
  } | null>(null);
  const [customPrompt, setCustomPrompt] = useState("");
  const [converting, setConverting] = useState(false);
  const [convertedYaml, setConvertedYaml] = useState("");
  const [convertedInfo, setConvertedInfo] = useState<{ count: number; steps: number } | null>(null);
  const [convertValidation, setConvertValidation] = useState<ValidationItem[]>([]);
  const [convertValidationSummary, setConvertValidationSummary] = useState<ValidationSummary | null>(null);
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
  const [scanValidation, setScanValidation] = useState<ValidationItem[]>([]);
  const [scanValidationSummary, setScanValidationSummary] = useState<ValidationSummary | null>(null);
  const scanWsRef = useRef<WebSocket | null>(null);
  // Track whether plan generation was already triggered to avoid double-calls
  const planTriggeredRef = useRef(false);
  // Document upload state
  const [userDocs, setUserDocs] = useState<DocumentItem[]>([]);
  const [userDocsMax, setUserDocsMax] = useState(3);
  const [docUploading, setDocUploading] = useState(false);
  const [docError, setDocError] = useState("");
  const [docDragOver, setDocDragOver] = useState(false);
  const docInputRef = useRef<HTMLInputElement>(null);
  // Scan log state
  const [scanLogs, setScanLogs] = useState<{ phase: string; message: string; level?: string; ts: number }[]>([]);
  const scanLogRef = useRef<HTMLDivElement>(null);

  // Auto-scroll scan log
  useEffect(() => {
    if (scanLogRef.current) {
      scanLogRef.current.scrollTop = scanLogRef.current.scrollHeight;
    }
  }, [scanLogs]);

  // Fetch billing info + documents
  useEffect(() => {
    if (user) {
      fetchBilling().then(setBilling).catch(() => {});
      listDocuments()
        .then((res) => {
          setUserDocs(res.documents);
          setUserDocsMax(res.max_allowed);
        })
        .catch(() => {});
    }
  }, [user]);

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
    }
  }, [authLoading, user, router]);

  if (authLoading || !user) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">{tc("loading")}</p>
      </div>
    );
  }

  const handleConvert = async () => {
    setError("");
    setConverting(true);
    setConvertedYaml("");
    setConvertedInfo(null);
    setConvertValidation([]);
    setConvertValidationSummary(null);

    try {
      const result = await convertScenario(url, customPrompt);
      setConvertedYaml(result.scenario_yaml);
      setConvertedInfo({ count: result.scenarios_count, steps: result.steps_total });
      setConvertValidation(result.validation || []);
      setConvertValidationSummary(result.validation_summary || null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Conversion failed";
      setError(translateApiError(msg, te));
    } finally {
      setConverting(false);
    }
  };

  const handleGenerateAdditional = async () => {
    setError("");
    setAdditionalConverting(true);
    setAdditionalYaml("");
    setAdditionalInfo(null);
    setAdditionalRelevance(null);

    try {
      const result = await convertScenario(url, additionalPrompt, "en", activeScan?.id);
      setAdditionalYaml(result.scenario_yaml);
      setAdditionalInfo({ count: result.scenarios_count, steps: result.steps_total });
      if (result.relevance) {
        setAdditionalRelevance(result.relevance);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Generation failed";
      setError(translateApiError(msg, te));
    } finally {
      setAdditionalConverting(false);
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
  const handleStartScan = async () => {
    setError("");
    setScanPhase("scanning");
    planTriggeredRef.current = false;
    setScanProgress({ pages: 0, max: 5, links: 0, forms: 0, buttons: 0, features: [], currentUrl: "" });
    setScanLogs([]);
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
        } else if (type === "scan_log") {
          setScanLogs((prev) => [
            ...prev,
            {
              phase: (data.phase as string) || "",
              message: (data.message as string) || "",
              level: (data.level as string) || undefined,
              ts: Date.now(),
            },
          ]);
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
    if (!activeScan || (selectedTests.size === 0 && !additionalYaml)) return;
    setError("");
    setScanExecuting(true);
    setScanValidation([]);
    setScanValidationSummary(null);

    try {
      if (selectedTests.size === 0 && additionalYaml) {
        // Only additional tests, skip scan execution
        const test = await createTest(url, "auto", additionalYaml);
        setActiveTest(test);
        setPhase("executing");
        setScanPhase("executing");
      } else if (additionalYaml) {
        // Both scan tests + additional: execute scan, merge YAMLs
        const result = await executeScanTests(
          activeScan.id,
          Array.from(selectedTests),
          authData,
          testData,
        );
        setScanValidation(result.validation || []);
        setScanValidationSummary(result.validation_summary || null);

        // Merge scan YAML + additional YAML
        const mergedYaml = result.scenario_yaml + "\n" + additionalYaml;
        const mergedTest = await createTest(url, "auto", mergedYaml);
        // Cancel the original scan test
        await cancelTest(result.test_id).catch(() => {});
        setActiveTest(mergedTest);
        setPhase("executing");
        setScanPhase("executing");
      } else {
        // Normal: only scan tests
        const result = await executeScanTests(
          activeScan.id,
          Array.from(selectedTests),
          authData,
          testData,
        );
        setScanValidation(result.validation || []);
        setScanValidationSummary(result.validation_summary || null);
        const test = await getTest(result.test_id);
        setActiveTest(test);
        setPhase("executing");
        setScanPhase("executing");
      }
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
    blog: ts("featureBlog"),
    signup: ts("featureSignup"),
    multilingual: ts("featureMultilingual"),
    spa: ts("featureSpa"),
    sticky_header: ts("featureStickyHeader"),
  };

  // -- Document handlers --
  const handleDocUpload = async (file: File) => {
    setDocError("");
    setDocUploading(true);
    try {
      const doc = await uploadUserDocument(file);
      setUserDocs((prev) => [doc, ...prev]);
    } catch (err) {
      setDocError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setDocUploading(false);
    }
  };

  const handleDocDelete = async (docId: number) => {
    try {
      await deleteDocument(docId);
      setUserDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      setDocError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleDocDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDocDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) handleDocUpload(files[0]);
  };

  const handleDocInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleDocUpload(files[0]);
      e.target.value = "";
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const isBusy = submitting || additionalConverting || (phase !== "idle" && phase !== "done");

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
        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700">
            {t("targetUrlLabel")}
          </label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            placeholder={t("urlPlaceholder")}
            className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
          />
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

        {/* Reference Documents */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            {t("refDocsLabel")}
          </label>
          <p className="mb-2 text-xs text-gray-400">{t("refDocsDesc")}</p>

          {/* Uploaded file list */}
          {userDocs.length > 0 && (
            <div className="mb-2 space-y-1.5">
              {userDocs.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm">&#128196;</span>
                    <span className="truncate text-sm text-gray-700">{doc.filename}</span>
                    <span className="shrink-0 text-xs text-gray-400">
                      {formatFileSize(doc.size_bytes)}
                    </span>
                    {doc.extracted_chars > 0 && (
                      <span className="shrink-0 text-[10px] text-green-600">
                        {doc.extracted_chars.toLocaleString()} chars
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDocDelete(doc.id)}
                    className="ml-2 shrink-0 text-gray-400 hover:text-red-500 text-sm"
                    title="Delete"
                  >
                    &#10005;
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Drop zone */}
          {userDocs.length < userDocsMax ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setDocDragOver(true); }}
              onDragLeave={() => setDocDragOver(false)}
              onDrop={handleDocDrop}
              onClick={() => docInputRef.current?.click()}
              className={`cursor-pointer rounded-lg border-2 border-dashed px-4 py-3 text-center transition-colors ${
                docDragOver
                  ? "border-blue-400 bg-blue-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
            >
              {docUploading ? (
                <p className="text-sm text-gray-500">{t("refDocsUploading")}</p>
              ) : (
                <>
                  <p className="text-sm text-gray-500">{t("refDocsDropHint")}</p>
                  <p className="mt-0.5 text-[10px] text-gray-400">{t("refDocsFormats")}</p>
                </>
              )}
              <input
                ref={docInputRef}
                type="file"
                className="hidden"
                accept=".md,.txt,.pdf,.docx,.png,.jpg,.jpeg"
                onChange={handleDocInputChange}
              />
            </div>
          ) : (
            <p className="text-xs text-amber-600">
              {t("refDocsMaxReached", { max: userDocsMax })}
            </p>
          )}

          {docError && (
            <p className="mt-1 text-xs text-red-500">{docError}</p>
          )}
        </div>

        {/* Direct mode: write tests without scanning */}
        {directMode ? (
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => setDirectMode(false)}
              className="text-sm text-teal-600 hover:text-teal-700 hover:underline"
            >
              &larr; {t("backToScan")}
            </button>
            <p className="text-xs text-gray-400">{t("tabCustomDesc")}</p>
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
                {/* Validation summary */}
                {convertValidationSummary && convertValidationSummary.total > 0 && (
                  <div className={`rounded-lg border px-4 py-2.5 text-sm ${
                    convertValidationSummary.percent >= 70
                      ? "border-green-200 bg-green-50 text-green-700"
                      : convertValidationSummary.percent >= 50
                      ? "border-amber-200 bg-amber-50 text-amber-700"
                      : "border-red-200 bg-red-50 text-red-700"
                  }`}>
                    <span className="font-medium">
                      {t("validationSummary", {
                        verified: convertValidationSummary.verified,
                        total: convertValidationSummary.total,
                        percent: convertValidationSummary.percent,
                      })}
                    </span>
                    {convertValidationSummary.percent < 50 && (
                      <p className="mt-1 text-xs">{t("validationLowQuality")}</p>
                    )}
                  </div>
                )}
                {/* Per-step validation badges */}
                {convertValidation.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {convertValidation.map((v, i) => (
                      <span
                        key={i}
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          v.status === "verified"
                            ? "bg-green-50 text-green-600"
                            : "bg-amber-50 text-amber-600"
                        }`}
                        title={v.closest_match ? `closest: ${v.closest_match}` : undefined}
                      >
                        {v.status === "verified" ? "\u2705" : "\u26A0\uFE0F"}{" "}
                        S{v.scenario_idx + 1}.{v.step}{" "}
                        {v.status === "verified" ? t("validationVerified") : t("validationUnverified")}
                      </span>
                    ))}
                  </div>
                )}
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
        ) : (
          /* Normal mode: Scan flow */
          <div className="space-y-4">
            {/* Skip scan link */}
            {scanPhase === "idle" && (
              <button
                type="button"
                onClick={() => setDirectMode(true)}
                className="text-sm text-blue-600 hover:text-blue-700 hover:underline"
              >
                {t("skipScan")} &rarr;
              </button>
            )}

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
                {/* Scan log area */}
                {scanLogs.length > 0 && (
                  <div className="mt-2">
                    <p className="mb-1 text-[10px] font-medium text-teal-700 uppercase">{ts("scanLogTitle")}</p>
                    <div
                      ref={scanLogRef}
                      className="max-h-40 overflow-y-auto rounded border border-teal-200 bg-white/60 px-3 py-2 text-[11px] font-mono leading-relaxed"
                    >
                      {scanLogs.map((log, i) => {
                        const phaseIcons: Record<string, string> = {
                          navigate: "\uD83C\uDF10",
                          extract: "\uD83D\uDD0D",
                          feature: "\u2699\uFE0F",
                          observe: "\uD83D\uDC41",
                          links: "\uD83D\uDD17",
                        };
                        const icon = phaseIcons[log.phase] || "\u25B6";
                        const color = log.level === "error"
                          ? "text-red-600"
                          : log.level === "warn"
                          ? "text-amber-600"
                          : "text-gray-700";
                        return (
                          <div key={i} className={`${color} ${log.message.startsWith("  →") ? "ml-4" : ""}`}>
                            {!log.message.startsWith("  →") && <span className="mr-1">{icon}</span>}
                            {log.message}
                          </div>
                        );
                      })}
                    </div>
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
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-gray-800">{ts("scanComplete")}</span>
                        {activeScan.summary.site_type && activeScan.summary.site_type.type !== "unknown" && (
                          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
                            {ts(`siteType_${activeScan.summary.site_type.type}` as Parameters<typeof ts>[0])}
                          </span>
                        )}
                      </div>
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
                    {/* Scan detail log (persisted or from session) */}
                    {(() => {
                      const logs = activeScan.logs?.length ? activeScan.logs : scanLogs;
                      if (!logs || logs.length === 0) return null;
                      return (
                        <details className="pt-1">
                          <summary className="cursor-pointer text-[10px] font-medium text-gray-500 uppercase hover:text-gray-700">
                            {ts("scanLogTitle")} ({logs.length})
                          </summary>
                          <div className="mt-1 max-h-48 overflow-y-auto rounded border border-gray-200 bg-white/60 px-3 py-2 text-[11px] font-mono leading-relaxed">
                            {logs.map((log, i) => {
                              const phaseIcons: Record<string, string> = {
                                navigate: "\uD83C\uDF10", extract: "\uD83D\uDD0D",
                                feature: "\u2699\uFE0F", observe: "\uD83D\uDC41",
                                links: "\uD83D\uDD17", scroll: "\uD83D\uDCC4",
                                accordion: "\uD83D\uDD3D",
                              };
                              const icon = phaseIcons[log.phase] || "\u25B6";
                              const color = log.level === "error" ? "text-red-600"
                                : log.level === "warn" ? "text-amber-600" : "text-gray-600";
                              return (
                                <div key={i} className={`${color} ${log.message.startsWith("  →") ? "ml-4" : ""}`}>
                                  {!log.message.startsWith("  →") && <span className="mr-1">{icon}</span>}
                                  {log.message}
                                </div>
                              );
                            })}
                          </div>
                        </details>
                      );
                    })()}
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
                          {isExpanded && (() => {
                            // Collect shared auth fields for this category (deduplicated)
                            const sharedAuthFields = new Map<string, { key: string; label: string; type: string; required: boolean }>();
                            const hasAnySelectedAuth = catTests.some((t) => selectedTests.has(t.id) && t.requires_auth);
                            if (hasAnySelectedAuth) {
                              // Default auth fields — always present for auth-required tests
                              sharedAuthFields.set("email", { key: "email", label: ts("authEmail"), type: "email", required: true });
                              sharedAuthFields.set("password", { key: "password", label: ts("authPassword"), type: "password", required: true });
                              // Merge/overwrite with plan-provided labels (from crawl data)
                              for (const t of catTests) {
                                if (t.requires_auth && t.auth_fields) {
                                  for (const f of t.auth_fields) {
                                    sharedAuthFields.set(f.key, f);
                                  }
                                }
                              }
                            }

                            return (
                              <div className="divide-y divide-gray-100">
                                {/* Category-level shared auth fields */}
                                {sharedAuthFields.size > 0 && (
                                  <div key="shared-auth" className="px-4 py-2.5">
                                    <div className="space-y-1.5 rounded-lg border border-amber-200 bg-amber-50/50 p-3">
                                      <p className="text-[10px] font-semibold text-amber-700 uppercase">{ts("sharedAuth")}</p>
                                      {Array.from(sharedAuthFields.values()).map((field) => (
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
                                  </div>
                                )}

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
                            );
                          })()}
                        </div>
                      );
                    })}

                    {/* Additional test requests (before execute button) */}
                    {scanPhase === "ready" && (
                      <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
                        <div>
                          <h4 className="text-sm font-medium text-gray-700">{t("additionalTests")}</h4>
                          <p className="text-xs text-gray-400 mt-0.5">{t("additionalTestsDesc")}</p>
                        </div>
                        <textarea
                          value={additionalPrompt}
                          onChange={(e) => setAdditionalPrompt(e.target.value)}
                          placeholder={t("additionalTestsPlaceholder")}
                          rows={3}
                          className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 focus:outline-none resize-none"
                        />
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={handleGenerateAdditional}
                            disabled={additionalConverting || !url || !additionalPrompt.trim() || isBusy}
                            className="whitespace-nowrap rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            {additionalConverting ? t("generatingScenario") : t("generateScenario")}
                          </button>
                          {additionalInfo && (
                            <span className="text-sm text-gray-500">
                              {t("additionalGenerated", { count: additionalInfo.count, steps: additionalInfo.steps })}
                            </span>
                          )}
                        </div>
                        {/* Relevance validation warning */}
                        {additionalRelevance && !additionalRelevance.valid && (
                          <div className={`rounded-lg border p-3 text-sm space-y-1 ${
                            additionalRelevance.feature_missing
                              ? "border-amber-300 bg-amber-50"
                              : "border-orange-300 bg-orange-50"
                          }`}>
                            <p className="font-medium text-amber-800">
                              {additionalRelevance.feature_missing ? "\u26A0\uFE0F " : "\u26A0\uFE0F "}
                              {additionalRelevance.reason}
                            </p>
                            {additionalRelevance.warnings.map((w, i) => (
                              <p key={i} className="text-xs text-amber-700 ml-5">• {w}</p>
                            ))}
                          </div>
                        )}
                        {/* Additional YAML preview */}
                        {additionalYaml && (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <p className="text-xs font-medium text-gray-600">{t("userRequestedTests")}</p>
                              {additionalRelevance && !additionalRelevance.valid && !additionalRelevance.feature_missing && (
                                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                                  {"\u26A0\uFE0F"} {t("unverifiedScenario")}
                                </span>
                              )}
                            </div>
                            <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3">
                              <pre className="whitespace-pre-wrap text-xs text-gray-700">{additionalYaml}</pre>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Execute button */}
                    <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
                      <span className="text-sm text-gray-600">
                        {selectedTests.size} {ts("selectedTests")}
                        {additionalInfo && additionalInfo.count > 0 && !(additionalRelevance?.feature_missing) && (
                          <span className={`ml-1 ${additionalRelevance && !additionalRelevance.valid ? "text-amber-600" : "text-blue-600"}`}>
                            + {additionalInfo.count}
                            {additionalRelevance && !additionalRelevance.valid && " \u26A0\uFE0F"}
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={handleExecuteScan}
                        disabled={(selectedTests.size === 0 && !additionalYaml) || scanExecuting || isBusy}
                        className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                      >
                        {scanExecuting ? ts("executing") : ts("runSelected")}
                      </button>
                    </div>

                    {/* Validation results after execute */}
                    {scanValidationSummary && scanValidationSummary.total > 0 && (
                      <div className="space-y-2">
                        <div className={`rounded-lg border px-4 py-2.5 text-sm ${
                          scanValidationSummary.percent >= 70
                            ? "border-green-200 bg-green-50 text-green-700"
                            : scanValidationSummary.percent >= 50
                            ? "border-amber-200 bg-amber-50 text-amber-700"
                            : "border-red-200 bg-red-50 text-red-700"
                        }`}>
                          <span className="font-medium">
                            {ts("validationSummary", {
                              verified: scanValidationSummary.verified,
                              total: scanValidationSummary.total,
                              percent: scanValidationSummary.percent,
                            })}
                          </span>
                          {scanValidationSummary.percent < 50 && (
                            <p className="mt-1 text-xs">{ts("validationLowQuality")}</p>
                          )}
                        </div>
                        {scanValidation.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {scanValidation.map((v, i) => (
                              <span
                                key={i}
                                className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                  v.status === "verified"
                                    ? "bg-green-50 text-green-600"
                                    : "bg-amber-50 text-amber-600"
                                }`}
                                title={v.closest_match ? `closest: ${v.closest_match}` : undefined}
                              >
                                {v.status === "verified" ? "\u2705" : "\u26A0\uFE0F"}{" "}
                                S{v.scenario_idx + 1}.{v.step}{" "}
                                {v.status === "verified" ? ts("validationVerified") : ts("validationUnverified")}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
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
