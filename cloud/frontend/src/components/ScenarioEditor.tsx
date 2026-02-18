"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { updateScenarios, approveTest } from "@/lib/api";
import ScenarioViewer from "./ScenarioViewer";

interface Props {
  testId: number;
  initialYaml: string;
  onApprove: () => void;
}

export default function ScenarioEditor({ testId, initialYaml, onApprove }: Props) {
  const t = useTranslations("scenarioEditor");
  const [yaml, setYaml] = useState(initialYaml);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [showEditor, setShowEditor] = useState(false);

  const handleSave = async () => {
    setError("");
    setSaving(true);
    setSaved(false);
    try {
      await updateScenarios(testId, yaml);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleRunTest = async () => {
    setError("");
    setApproving(true);
    try {
      await updateScenarios(testId, yaml);
      await approveTest(testId);
      onApprove();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setApproving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">{t("title")}</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowEditor((v) => !v)}
            className={`rounded-lg border px-3 py-1 text-xs font-medium transition-colors ${
              showEditor
                ? "border-gray-400 bg-gray-100 text-gray-700"
                : "border-gray-200 text-gray-500 hover:bg-gray-50"
            }`}
          >
            {showEditor ? t("visualView") : t("editYaml")}
          </button>
          <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
            {t("review")}
          </span>
        </div>
      </div>

      {/* Visual view (default) */}
      {!showEditor && <ScenarioViewer yamlText={yaml} />}

      {/* YAML editor (toggled) */}
      {showEditor && (
        <div className="space-y-3">
          <textarea
            value={yaml}
            onChange={(e) => {
              setYaml(e.target.value);
              setSaved(false);
            }}
            className="w-full rounded-lg border border-gray-300 bg-gray-50 p-3 font-mono text-xs leading-relaxed text-gray-800 focus:border-blue-500 focus:outline-none"
            rows={16}
            spellCheck={false}
          />
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {saving ? t("saving") : saved ? t("saved") : t("save")}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-50 p-2 text-xs text-red-600">{error}</div>
      )}

      {/* Action button */}
      <button
        onClick={handleRunTest}
        disabled={approving || !yaml.trim()}
        className="w-full rounded-lg bg-green-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
      >
        {approving ? t("starting") : t("runTest")}
      </button>
    </div>
  );
}
