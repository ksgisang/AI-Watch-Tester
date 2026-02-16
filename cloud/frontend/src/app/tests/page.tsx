"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  const [tests, setTests] = useState<TestItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
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
    try {
      const data = await listTests(page, 20);
      setTests(data.tests);
      setTotal(data.total);
    } catch {
      // Ignore errors silently
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
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Test History</h1>
        <button
          onClick={() => router.push("/dashboard")}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          New Test
        </button>
      </div>

      {/* Filter */}
      <div className="mb-4 flex gap-2">
        {["all", "passed", "failed"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              filter === f
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {f === "all" ? "All" : f === "passed" ? "Passed" : "Failed"}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-400">
          {total} total tests
        </span>
      </div>

      {/* List */}
      {loading ? (
        <p className="py-8 text-center text-gray-500">Loading...</p>
      ) : filtered.length === 0 ? (
        <p className="py-8 text-center text-gray-500">
          No tests found.{" "}
          <button
            onClick={() => router.push("/dashboard")}
            className="text-blue-600 hover:underline"
          >
            Run your first test
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
                    ` · ${test.steps_completed}/${test.steps_total} steps`}
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
            Prev
          </button>
          <span className="px-2 py-1 text-sm text-gray-500">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * 20 >= total}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
