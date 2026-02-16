"use client";

import { useEffect, useRef, useState } from "react";
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
}

interface Props {
  testId: number;
  onComplete?: (passed: boolean) => void;
}

export default function TestProgress({ testId, onComplete }: Props) {
  const [events, setEvents] = useState<WSEvent[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [status, setStatus] = useState<"connecting" | "running" | "done">(
    "connecting"
  );
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = connectTestWS(
      testId,
      (data) => {
        const evt = data as unknown as WSEvent;
        setEvents((prev) => [...prev, evt]);

        switch (evt.type) {
          case "test_start":
            setStatus("running");
            break;
          case "scenarios_generated":
            if (evt.steps_total) setTotalSteps(evt.steps_total);
            break;
          case "step_start":
            if (evt.step) setCurrentStep(evt.step);
            if (evt.total) setTotalSteps(evt.total);
            break;
          case "step_done":
          case "step_fail":
            break;
          case "test_complete":
            setStatus("done");
            onComplete?.(!!evt.passed);
            break;
          case "test_fail":
            setStatus("done");
            onComplete?.(false);
            break;
        }
      },
      () => {
        if (status !== "done") setStatus("done");
      }
    );

    wsRef.current = ws;
    return () => ws.close();
  }, [testId]);

  const progress =
    totalSteps > 0 ? Math.round((currentStep / totalSteps) * 100) : 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">Test Progress</h3>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            status === "connecting"
              ? "bg-yellow-100 text-yellow-700"
              : status === "running"
              ? "bg-blue-100 text-blue-700"
              : "bg-gray-100 text-gray-700"
          }`}
        >
          {status === "connecting"
            ? "Connecting..."
            : status === "running"
            ? "Running"
            : "Complete"}
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-3 h-2 rounded-full bg-gray-100">
        <div
          className="h-2 rounded-full bg-blue-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="mb-3 text-xs text-gray-500">
        {currentStep} / {totalSteps} steps ({progress}%)
      </p>

      {/* Event log */}
      <div className="max-h-48 space-y-1 overflow-y-auto">
        {events.map((evt, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <span className="mt-0.5">
              {evt.type === "step_done" ? (
                <span className="text-green-500">&#10003;</span>
              ) : evt.type === "step_fail" ? (
                <span className="text-red-500">&#10007;</span>
              ) : evt.type === "test_complete" ? (
                <span className="text-green-600">&#9679;</span>
              ) : evt.type === "test_fail" ? (
                <span className="text-red-600">&#9679;</span>
              ) : (
                <span className="text-gray-400">&#8226;</span>
              )}
            </span>
            <span className="text-gray-600">
              {evt.type === "test_start" && "Test started"}
              {evt.type === "scenarios_generated" &&
                `${evt.count} scenario(s) generated (${evt.steps_total} steps)`}
              {evt.type === "step_start" &&
                `Step ${evt.step}: ${evt.description || "..."}`}
              {evt.type === "step_done" &&
                `Step ${evt.step}: passed`}
              {evt.type === "step_fail" &&
                `Step ${evt.step}: failed${evt.error ? ` — ${evt.error}` : ""}`}
              {evt.type === "test_complete" &&
                `Test ${evt.passed ? "PASSED" : "FAILED"}`}
              {evt.type === "test_fail" &&
                `Test FAILED${evt.error ? `: ${evt.error}` : ""}`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
