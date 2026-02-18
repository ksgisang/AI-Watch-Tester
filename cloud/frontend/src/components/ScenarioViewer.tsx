"use client";

import { useState, useMemo } from "react";
import { useTranslations } from "next-intl";
import yaml from "js-yaml";

/* ------------------------------------------------------------------ */
/* Types for parsed YAML scenarios                                     */
/* ------------------------------------------------------------------ */

interface ScenarioStep {
  step: number;
  action: string;
  description?: string;
  value?: string;
  target?: { text?: string };
  assert_type?: string;
  expected?: Array<{ type?: string; value?: string }>;
}

interface ParsedScenario {
  id: string;
  name: string;
  description?: string;
  tags?: string[];
  steps: ScenarioStep[];
  expected_result?: Array<{ type?: string; value?: string } | string>;
}

/* ------------------------------------------------------------------ */
/* Step → human-readable text                                          */
/* ------------------------------------------------------------------ */

const ACTION_ICONS: Record<string, string> = {
  navigate: "\u{1F310}",
  find_and_click: "\u{1F446}",
  find_and_type: "\u2328\uFE0F",
  type_text: "\u2328\uFE0F",
  press_key: "\u2328\uFE0F",
  assert: "\u2705",
  wait: "\u23F3",
  screenshot: "\u{1F4F8}",
};

function describeStep(
  step: ScenarioStep,
  t: (key: string, values?: Record<string, string>) => string,
): { icon: string; text: string } {
  const icon = ACTION_ICONS[step.action] || "\u25B6\uFE0F";

  switch (step.action) {
    case "navigate":
      return { icon, text: t("actionNavigate", { url: step.value || "..." }) };

    case "find_and_click":
      return {
        icon,
        text: t("actionClick", { target: step.target?.text || step.value || "element" }),
      };

    case "find_and_type":
      return {
        icon,
        text: t("actionType", {
          target: step.target?.text || "field",
          value: step.value || "...",
        }),
      };

    case "type_text":
      return { icon, text: t("actionTypeText", { value: step.value || "..." }) };

    case "press_key":
      return { icon, text: t("actionPressKey", { key: step.value || "key" }) };

    case "assert": {
      const exp = step.expected?.[0];
      const assertType = exp?.type || step.assert_type;
      const assertValue = exp?.value || step.value || "...";
      if (assertType === "text_visible")
        return { icon, text: t("actionAssertVisible", { text: assertValue }) };
      if (assertType === "url_contains")
        return { icon, text: t("actionAssertUrl", { text: assertValue }) };
      return { icon, text: t("actionAssert", { description: step.description || "assertion" }) };
    }

    case "wait": {
      const ms = parseInt(step.value || "1000", 10);
      const seconds = (ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 1);
      return { icon, text: t("actionWait", { seconds }) };
    }

    case "screenshot":
      return { icon, text: t("actionScreenshot") };

    default:
      return { icon, text: t("actionDefault", { description: step.description || step.action }) };
  }
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

interface Props {
  yamlText: string;
}

export default function ScenarioViewer({ yamlText }: Props) {
  const t = useTranslations("scenarioViewer");
  const [expandedCode, setExpandedCode] = useState<Set<number>>(new Set());

  const scenarios: ParsedScenario[] = useMemo(() => {
    try {
      const parsed = yaml.load(yamlText);
      if (Array.isArray(parsed)) return parsed;
      if (parsed && typeof parsed === "object") return [parsed as ParsedScenario];
      return [];
    } catch {
      return [];
    }
  }, [yamlText]);

  if (scenarios.length === 0) return null;

  const toggleCode = (index: number) => {
    setExpandedCode((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const totalSteps = scenarios.reduce((sum, s) => sum + (s.steps?.length || 0), 0);

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-3">
        <span className="text-lg">{"\u{1F916}"}</span>
        <p className="text-sm font-medium text-blue-800">
          {t("summary", { count: String(scenarios.length) })}
        </p>
        <span className="ml-auto rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-700">
          {t("stepsCount", { count: String(totalSteps) })}
        </span>
      </div>

      {/* Scenario cards */}
      {scenarios.map((scenario, si) => (
        <div
          key={si}
          className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
        >
          {/* Card header */}
          <div className="border-b border-gray-100 px-4 py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-gray-900">
                  <span className="mr-1.5 text-gray-400">{scenario.id}</span>
                  {scenario.name}
                </h3>
                {scenario.description && (
                  <p className="mt-0.5 text-xs text-gray-500">{scenario.description}</p>
                )}
              </div>
              <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                {t("stepsCount", { count: String(scenario.steps?.length || 0) })}
              </span>
            </div>

            {/* Tags */}
            {scenario.tags && scenario.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {scenario.tags.map((tag, ti) => (
                  <span
                    key={ti}
                    className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Steps */}
          <div className="divide-y divide-gray-50 px-4">
            {scenario.steps?.map((step, i) => {
              const { icon, text } = describeStep(step, t);
              return (
                <div key={i} className="flex items-start gap-3 py-2.5">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-600">
                    {step.step}
                  </span>
                  <div className="min-w-0 pt-0.5">
                    <p className="text-sm text-gray-700">
                      <span className="mr-1.5">{icon}</span>
                      {text}
                    </p>
                    {step.description && step.action !== "navigate" && step.action !== "screenshot" && (
                      <p className="mt-0.5 text-xs text-gray-400">{step.description}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Expected results */}
          {scenario.expected_result && scenario.expected_result.length > 0 && (
            <div className="border-t border-gray-100 bg-green-50/50 px-4 py-2.5">
              <p className="text-xs font-medium text-green-700">{t("expectedResults")}</p>
              <ul className="mt-1 space-y-0.5">
                {scenario.expected_result.map((er, ei) => (
                  <li key={ei} className="text-xs text-green-600">
                    {"\u2705"}{" "}
                    {typeof er === "string" ? er : er.value || JSON.stringify(er)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Toggle code */}
          <div className="border-t border-gray-100 px-4 py-2">
            <button
              onClick={() => toggleCode(si)}
              className="text-xs font-medium text-gray-400 hover:text-gray-600"
            >
              {expandedCode.has(si) ? t("hideCode") : t("showCode")}
            </button>
            {expandedCode.has(si) && (
              <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-gray-50 p-3 text-xs leading-relaxed text-gray-600">
                {yaml.dump(scenario, { flowLevel: -1 })}
              </pre>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
