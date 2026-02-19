"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import { listTests, type TestItem } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-yellow-100 text-yellow-700",
  running: "bg-blue-100 text-blue-700",
  done: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

export default function TestsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const t = useTranslations("tests");
  const tc = useTranslations("common");
  const [tests, setTests] = useState<TestItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (user) fetchTests();
  }, [user, authLoading, page]);

  const fetchTests = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTests(page, 20);
      setTests(data.tests);
      setTotal(data.total);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load tests";
      if (msg.includes("401") || msg.includes("Not authenticated")) {
        router.push("/login");
        return;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const filtered =
    filter === "all"
      ? tests
      : tests.filter((t) =>
          filter === "passed" ? t.status === "done" : t.status === "failed"
        );

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">{tc("loading")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        <button
          onClick={() => router.push("/dashboard")}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          {t("newTest")}
        </button>
      </div>

      {/* Filter */}
      <div className="mb-4 flex gap-2">
        {(["all", "passed", "failed"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              filter === f
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {f === "all" ? t("filterAll") : f === "passed" ? t("filterPassed") : t("filterFailed")}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-400">
          {t("totalTests", { total })}
        </span>
      </div>

      {/* List */}
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={fetchTests}
            className="mt-2 text-sm text-red-600 hover:underline"
          >
            {tc("retry") ?? "Retry"}
          </button>
        </div>
      ) : loading ? (
        <p className="py-8 text-center text-gray-500">{tc("loading")}</p>
      ) : filtered.length === 0 ? (
        <p className="py-8 text-center text-gray-500">
          {t("noTests")}{" "}
          <button
            onClick={() => router.push("/dashboard")}
            className="text-blue-600 hover:underline"
          >
            {t("firstTest")}
          </button>
        </p>
      ) : (
        <div className="space-y-2">
          {filtered.map((test) => (
            <button
              key={test.id}
              onClick={() => router.push(`/tests/${test.id}`)}
              className="flex w-full items-center justify-between rounded-lg border border-gray-200 p-4 text-left hover:bg-gray-50"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">
                  {test.target_url}
                </p>
                <p className="mt-0.5 text-xs text-gray-500">
                  #{test.id} &middot;{" "}
                  {new Date(test.created_at).toLocaleString()}
                  {test.steps_total > 0 &&
                    ` · ${t("stepsInfo", { completed: test.steps_completed, total: test.steps_total })}`}
                </p>
              </div>
              <span
                className={`ml-4 rounded-full px-2 py-0.5 text-xs font-medium ${
                  STATUS_COLORS[test.status] || "bg-gray-100 text-gray-600"
                }`}
              >
                {test.status}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > 20 && (
        <div className="mt-4 flex justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            {t("prev")}
          </button>
          <span className="px-2 py-1 text-sm text-gray-500">{t("pageLabel", { page })}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * 20 >= total}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            {t("next")}
          </button>
        </div>
      )}
    </div>
  );
}
