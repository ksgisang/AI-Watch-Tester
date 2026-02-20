"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { connectTestWS } from "@/lib/api";

interface WSEvent {
  type: string;
  step?: number;
  total?: number;
  description?: string;
  status?: string;
  error?: string;
  passed?: boolean;
  count?: number;
  steps_total?: number;
  image?: string;
  timing?: string;
  phase?: string;
  elapsed_ms?: number;
}

type StepState = "pending" | "running" | "passed" | "failed" | "timeout";

interface StepInfo {
  num: number;
  description: string;
  state: StepState;
  error?: string;
  elapsedMs?: number;
}

interface Props {
  testId: number;
  onComplete?: (passed: boolean) => void;
  onScenariosReady?: (testId: number) => void;
}

export default function TestProgress({ testId, onComplete, onScenariosReady }: Props) {
  const t = useTranslations("progress");
  const [events, setEvents] = useState<WSEvent[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [status, setStatus] = useState<
    "connecting" | "waiting" | "generating" | "running" | "passed" | "failed"
  >("connecting");
  const [liveImage, setLiveImage] = useState<string | null>(null);
  const [stepLabel, setStepLabel] = useState("");
  const [steps, setSteps] = useState<StepInfo[]>([]);
  const [showEventLog, setShowEventLog] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const testStartedRef = useRef(false);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const connectWS = () => {
      const ws = connectTestWS(
        testId,
        (data) => {
          if (!mountedRef.current) return;
          const evt = data as unknown as WSEvent;

          // Screenshot events update live view only (don't add to log)
          if (evt.type === "screenshot") {
            if (evt.image) setLiveImage(evt.image);
            return;
          }

          setEvents((prev) => [...prev, evt]);

          switch (evt.type) {
            case "test_start":
              testStartedRef.current = true;
              if (evt.phase === "generate") {
                setStatus("generating");
                setStepLabel(t("generatingScenarios"));
              } else {
                setStatus("running");
                setStepLabel(t("startingTest"));
              }
              break;
            case "scenarios_ready":
              setStepLabel(t("scenariosReady"));
              onScenariosReady?.(testId);
              break;
            case "scenarios_generated":
              if (evt.steps_total) {
                setTotalSteps(evt.steps_total);
                // Initialize step placeholders
                setSteps(
                  Array.from({ length: evt.steps_total }, (_, i) => ({
                    num: i + 1,
                    description: `Step ${i + 1}`,
                    state: "pending" as StepState,
                  }))
                );
              }
              setStepLabel(t("scenariosGenerated", { count: evt.count ?? 0 }));
              break;
            case "step_start": {
              const stepNum = evt.step ?? 0;
              if (stepNum) setCurrentStep(stepNum);
              if (evt.total && totalSteps === 0) {
                setTotalSteps(evt.total);
                // Initialize if not yet done
                setSteps((prev) => {
                  if (prev.length === 0) {
                    return Array.from({ length: evt.total! }, (_, i) => ({
                      num: i + 1,
                      description: `Step ${i + 1}`,
                      state: "pending" as StepState,
                    }));
                  }
                  return prev;
                });
              }
              const desc = evt.description || `Step ${stepNum}`;
              setStepLabel(desc);
              // Update step state
              setSteps((prev) =>
                prev.map((s) =>
                  s.num === stepNum ? { ...s, state: "running", description: desc } : s
                )
              );
              break;
            }
            case "step_done": {
              const stepNum = evt.step ?? 0;
              setSteps((prev) =>
                prev.map((s) =>
                  s.num === stepNum
                    ? { ...s, state: "passed", elapsedMs: evt.elapsed_ms }
                    : s
                )
              );
              break;
            }
            case "step_fail": {
              const stepNum = evt.step ?? 0;
              const isTimeout = evt.error?.toLowerCase().includes("timed out") ?? false;
              setSteps((prev) =>
                prev.map((s) =>
                  s.num === stepNum
                    ? { ...s, state: isTimeout ? "timeout" : "failed", error: evt.error }
                    : s
                )
              );
              break;
            }
            case "test_complete":
              setStatus(evt.passed ? "passed" : "failed");
              setStepLabel(evt.passed ? t("evtTestPassed") : t("evtTestFailed"));
              onComplete?.(!!evt.passed);
              break;
            case "test_fail":
              setStatus("failed");
              setStepLabel(t("evtTestFailed"));
              onComplete?.(false);
              break;
          }
        },
        () => {
          if (!mountedRef.current) return;
          // If test hasn't started yet, show "waiting" and auto-reconnect
          if (!testStartedRef.current) {
            setStatus("waiting");
            setStepLabel(t("waitingForRunner"));
            reconnectRef.current = setTimeout(() => {
              if (mountedRef.current) connectWS();
            }, 3000);
          } else {
            // Test was running — real disconnect means failure
            setStatus("failed");
          }
        }
      );

      wsRef.current = ws;
    };

    connectWS();

    return () => {
      mountedRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [testId]);

  // Auto-scroll event log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events]);

  const progress =
    totalSteps > 0 ? Math.round((currentStep / totalSteps) * 100) : 0;

  const renderEventText = (evt: WSEvent): string => {
    switch (evt.type) {
      case "test_start":
        return t("evtTestStarted");
      case "scenarios_ready":
        return t("evtScenariosReady");
      case "scenarios_generated":
        return t("evtScenariosGenerated", { count: evt.count ?? 0, total: evt.steps_total ?? 0 });
      case "step_start":
        return t("evtStepStart", { step: evt.step ?? 0, description: evt.description || "..." });
      case "step_done":
        return t("evtStepPassed", { step: evt.step ?? 0 });
      case "step_fail":
        return evt.error
          ? t("evtStepFailedError", { step: evt.step ?? 0, error: evt.error })
          : t("evtStepFailed", { step: evt.step ?? 0 });
      case "test_complete":
        return evt.passed ? t("evtTestPassed") : t("evtTestFailed");
      case "test_fail":
        return evt.error
          ? t("evtTestFailedError", { error: evt.error })
          : t("evtTestFailed");
      default:
        return evt.type;
    }
  };

  const stepIcon = (state: StepState) => {
    switch (state) {
      case "pending":
        return <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-gray-300 text-xs text-gray-400">&#9675;</span>;
      case "running":
        return <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border-2 border-blue-500 text-xs text-blue-500 animate-spin border-t-transparent" />;
      case "passed":
        return <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-green-100 text-xs text-green-600">&#10003;</span>;
      case "failed":
        return <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-red-100 text-xs text-red-600">&#10007;</span>;
      case "timeout":
        return <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-orange-100 text-xs text-orange-600">&#9201;</span>;
    }
  };

  const stepStatusText = (state: StepState) => {
    switch (state) {
      case "pending": return t("stepPending");
      case "running": return t("stepRunning");
      case "passed": return t("stepPassed");
      case "failed": return t("stepFailed");
      case "timeout": return t("stepTimeout");
    }
  };

  return (
    <div className="space-y-3">
      {/* Live View — screenshot stream */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-gray-900">
        {/* Top bar */}
        <div className="flex items-center justify-between bg-gray-800 px-3 py-1.5">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                status === "generating"
                  ? "animate-pulse bg-purple-400"
                  : status === "running"
                  ? "animate-pulse bg-green-400"
                  : status === "connecting" || status === "waiting"
                  ? "animate-pulse bg-yellow-400"
                  : status === "passed"
                  ? "bg-green-400"
                  : "bg-red-400"
              }`}
            />
            <span className="text-xs text-gray-300">
              {status === "connecting"
                ? t("connecting")
                : status === "waiting"
                ? t("waiting")
                : status === "generating"
                ? t("generating")
                : status === "running"
                ? t("live")
                : status === "passed"
                ? t("passed")
                : t("failed")}
            </span>
          </div>
          <span className="text-xs text-gray-500">
            {stepLabel}
          </span>
        </div>

        {/* Screenshot area */}
        <div className="relative flex items-center justify-center bg-gray-900"
             style={{ minHeight: "280px" }}>
          {liveImage ? (
            <img
              src={liveImage}
              alt="Live browser view"
              className="w-full object-contain"
              style={{ maxHeight: "400px" }}
            />
          ) : (
            <div className="flex flex-col items-center gap-2 py-12">
              <div className={`h-8 w-8 rounded-full border-2 border-t-transparent ${
                status === "connecting" || status === "running" || status === "waiting"
                  ? "animate-spin border-blue-400"
                  : status === "generating"
                  ? "animate-spin border-purple-400"
                  : "border-gray-600"
              }`} />
              <p className="text-sm text-gray-500">
                {status === "connecting"
                  ? t("connectingRunner")
                  : status === "waiting"
                  ? t("waitingForRunner")
                  : status === "generating"
                  ? t("generatingScenarios")
                  : status === "running"
                  ? t("waitingScreenshot")
                  : t("noScreenshot")}
              </p>
              {(status === "connecting" || status === "waiting") && (
                <p className="text-xs text-gray-400">{t("screenshotHint")}</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Progress bar + step count */}
      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="mb-2 flex items-center justify-between text-xs text-gray-500">
          <span>{t("stepsProgress", { current: currentStep, total: totalSteps })}</span>
          <span>{progress}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-100">
          <div
            className={`h-1.5 rounded-full transition-all duration-300 ${
              status === "passed"
                ? "bg-green-500"
                : status === "failed"
                ? "bg-red-400"
                : status === "connecting" || status === "waiting"
                ? "bg-gray-300"
                : "bg-blue-500"
            }`}
            style={{ width: `${status === "passed" || status === "failed" ? 100 : status === "connecting" || status === "waiting" ? 5 : progress}%` }}
          />
        </div>
      </div>

      {/* Step-by-step indicators */}
      {steps.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-3">
          <h4 className="mb-2 text-xs font-medium text-gray-500">{t("stepsOverview")}</h4>
          <div className="space-y-0.5 max-h-64 overflow-y-auto">
            {steps.map((step) => (
              <div key={step.num}>
                <div
                  className={`flex items-center gap-2 rounded px-2 py-1 text-xs transition-colors ${
                    step.state === "running" ? "bg-blue-50" : ""
                  }`}
                >
                  {stepIcon(step.state)}
                  <span className="font-medium text-gray-700 w-8 flex-shrink-0">
                    {step.num}.
                  </span>
                  <span className="flex-1 text-gray-600 truncate">
                    {step.description}
                  </span>
                  <span className={`flex-shrink-0 text-[10px] font-medium ${
                    step.state === "passed" ? "text-green-600"
                      : step.state === "failed" ? "text-red-600"
                      : step.state === "timeout" ? "text-orange-600"
                      : step.state === "running" ? "text-blue-600"
                      : "text-gray-400"
                  }`}>
                    {stepStatusText(step.state)}
                    {step.elapsedMs != null && ` (${(step.elapsedMs / 1000).toFixed(1)}s)`}
                  </span>
                </div>
                {/* Inline error detail for failed/timeout steps */}
                {step.error && (
                  <details open className="ml-9 mr-2 mb-1">
                    <summary className="cursor-pointer text-[10px] font-medium text-red-500 select-none">
                      {t("failureReason")}
                    </summary>
                    <div className="mt-0.5 rounded bg-red-50 border border-red-100 px-2 py-1.5 text-xs text-red-700 font-mono whitespace-pre-wrap break-all">
                      {step.error}
                    </div>
                  </details>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Event log (collapsible) */}
      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <button
          type="button"
          onClick={() => setShowEventLog((v) => !v)}
          className="mb-1 flex w-full items-center justify-between text-xs font-medium text-gray-500 hover:text-gray-700"
        >
          <span>{t("eventLog")}</span>
          <span className="text-[10px]">{showEventLog ? "▲" : "▼"} ({events.length})</span>
        </button>
        {showEventLog && (
          <div ref={logRef} className="max-h-36 space-y-1 overflow-y-auto">
            {events.map((evt, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 flex-shrink-0">
                  {evt.type === "step_done" ? (
                    <span className="text-green-500">&#10003;</span>
                  ) : evt.type === "step_fail" ? (
                    <span className="text-red-500">&#10007;</span>
                  ) : evt.type === "test_complete" ? (
                    <span className={evt.passed ? "text-green-600" : "text-red-600"}>&#9679;</span>
                  ) : evt.type === "test_fail" ? (
                    <span className="text-red-600">&#9679;</span>
                  ) : (
                    <span className="text-gray-400">&#8226;</span>
                  )}
                </span>
                <span className="text-gray-600">
                  {renderEventText(evt)}
                </span>
              </div>
            ))}
            {events.length === 0 && (
              <p className="text-xs text-gray-400">{t("waitingEvents")}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
