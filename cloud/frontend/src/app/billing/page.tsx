"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import { fetchBilling, fetchBillingPortal, type BillingInfo } from "@/lib/api";

export default function BillingPage() {
  const { user } = useAuth();
  const t = useTranslations("billing");
  const tc = useTranslations("common");

  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    fetchBilling()
      .then(setBilling)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [user]);

  const handleManage = async () => {
    try {
      const { url } = await fetchBillingPortal();
      window.open(url, "_blank");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open portal");
    }
  };

  if (!user) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-gray-500">{t("loginRequired")}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">{tc("loading")}</p>
      </div>
    );
  }

  const tierLabel = billing?.tier?.toUpperCase() || "FREE";
  const tierColor =
    billing?.tier === "team"
      ? "bg-purple-100 text-purple-700"
      : billing?.tier === "pro"
      ? "bg-blue-100 text-blue-700"
      : "bg-gray-100 text-gray-700";

  const usagePercent = billing
    ? Math.min(100, Math.round((billing.usage.monthly_used / billing.usage.monthly_limit) * 100))
    : 0;

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mb-8 text-sm text-gray-500">{t("subtitle")}</p>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</div>
      )}

      {billing && (
        <div className="space-y-6">
          {/* Current Plan */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="mb-3 text-lg font-semibold text-gray-900">{t("currentPlan")}</h2>
            <span className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${tierColor}`}>
              {tierLabel}
            </span>
            {billing.plan_expires_at && (
              <p className="mt-2 text-sm text-gray-500">
                {t("expiresAt", {
                  date: new Date(billing.plan_expires_at).toLocaleDateString(),
                })}
              </p>
            )}
          </div>

          {/* Usage */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="mb-3 text-lg font-semibold text-gray-900">{t("usage")}</h2>

            {/* Monthly tests */}
            <p className="mb-2 text-sm text-gray-700">
              {t("testsThisMonth", {
                used: billing.usage.monthly_used,
                limit: billing.usage.monthly_limit,
              })}
            </p>
            <div className="mb-4 h-2 overflow-hidden rounded-full bg-gray-200">
              <div
                className={`h-full rounded-full transition-all ${
                  usagePercent >= 90 ? "bg-red-500" : usagePercent >= 70 ? "bg-yellow-500" : "bg-blue-500"
                }`}
                style={{ width: `${usagePercent}%` }}
              />
            </div>

            {/* Concurrent */}
            <p className="text-sm text-gray-700">
              {t("concurrentTests", {
                active: billing.usage.active_count,
                limit: billing.usage.concurrent_limit,
              })}
            </p>
          </div>

          {/* Actions */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="mb-3 text-lg font-semibold text-gray-900">{t("subscription")}</h2>
            {billing.tier === "free" ? (
              <div>
                <p className="mb-3 text-sm text-gray-600">{t("noSubscription")}</p>
                <p className="mb-4 text-sm text-gray-500">{t("upgradePrompt")}</p>
                <Link
                  href="/pricing"
                  className="inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
                >
                  {t("upgrade")}
                </Link>
              </div>
            ) : (
              <button
                onClick={handleManage}
                className="rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {t("manageSub")}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
