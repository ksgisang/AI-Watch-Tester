"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { fetchHealth, type HealthResponse } from "@/lib/api";

function StatusDot({ status }: { status: string }) {
  const color =
    status === "up" || status === "healthy"
      ? "bg-green-500"
      : status === "degraded"
        ? "bg-yellow-500"
        : status === "down"
          ? "bg-red-500"
          : "bg-gray-400";

  return (
    <span className={`inline-block h-3 w-3 rounded-full ${color}`} />
  );
}

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export default function StatusPage() {
  const t = useTranslations("status");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadHealth = async () => {
    try {
      const data = await fetchHealth();
      setHealth(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
    const interval = setInterval(loadHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mb-8 text-sm text-gray-500">{t("subtitle")}</p>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-gray-500">{t("checking")}</p>
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4">
          <div className="flex items-center gap-2">
            <StatusDot status="down" />
            <span className="font-medium text-red-800">{t("unreachable")}</span>
          </div>
          <p className="mt-1 text-sm text-red-600">{error}</p>
        </div>
      )}

      {health && (
        <>
          {/* Overall status */}
          <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <StatusDot status={health.status} />
                <span className="text-lg font-semibold text-gray-900">
                  {health.status === "healthy"
                    ? t("allOperational")
                    : health.status === "degraded"
                      ? t("partialOutage")
                      : t("majorOutage")}
                </span>
              </div>
              <span className="text-sm text-gray-500">
                {t("uptime")}: {formatUptime(health.uptime_seconds)}
              </span>
            </div>
          </div>

          {/* Component checks */}
          <div className="space-y-3">
            {/* Database */}
            <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-5 py-4">
              <div className="flex items-center gap-3">
                <StatusDot status={health.checks.database.status} />
                <span className="font-medium text-gray-800">{t("database")}</span>
              </div>
              <span className={`text-sm font-medium ${
                health.checks.database.status === "up" ? "text-green-600" : "text-red-600"
              }`}>
                {health.checks.database.status === "up" ? t("operational") : t("downLabel")}
              </span>
            </div>

            {/* Worker */}
            <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-5 py-4">
              <div className="flex items-center gap-3">
                <StatusDot status={health.checks.worker.status} />
                <span className="font-medium text-gray-800">{t("worker")}</span>
              </div>
              <div className="flex items-center gap-4">
                {health.checks.worker.status === "up" && (
                  <span className="text-xs text-gray-500">
                    {t("workerSlots", {
                      active: health.checks.worker.active_tests ?? 0,
                      max: health.checks.worker.max_concurrent ?? 0,
                    })}
                  </span>
                )}
                <span className={`text-sm font-medium ${
                  health.checks.worker.status === "up" ? "text-green-600" : "text-red-600"
                }`}>
                  {health.checks.worker.status === "up" ? t("operational") : t("downLabel")}
                </span>
              </div>
            </div>

            {/* AI Provider */}
            <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-5 py-4">
              <div className="flex items-center gap-3">
                <StatusDot status={health.checks.ai_provider.status} />
                <div>
                  <span className="font-medium text-gray-800">{t("aiProvider")}</span>
                  {health.checks.ai_provider.provider && (
                    <span className="ml-2 text-xs text-gray-400">
                      ({health.checks.ai_provider.provider})
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-4">
                {health.checks.ai_provider.models_available !== undefined && (
                  <span className="text-xs text-gray-500">
                    {t("modelsAvailable", { count: health.checks.ai_provider.models_available })}
                  </span>
                )}
                <span className={`text-sm font-medium ${
                  health.checks.ai_provider.status === "up"
                    ? "text-green-600"
                    : health.checks.ai_provider.status === "degraded"
                      ? "text-yellow-600"
                      : "text-red-600"
                }`}>
                  {health.checks.ai_provider.status === "up"
                    ? t("operational")
                    : health.checks.ai_provider.status === "degraded"
                      ? t("degradedLabel")
                      : t("downLabel")}
                </span>
              </div>
            </div>
          </div>

          {/* Refresh note */}
          <p className="mt-6 text-center text-xs text-gray-400">
            {t("autoRefresh")}
          </p>
        </>
      )}
    </div>
  );
}
