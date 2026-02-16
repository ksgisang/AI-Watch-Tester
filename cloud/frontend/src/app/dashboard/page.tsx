"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import TestProgress from "@/components/TestProgress";
import { createTest, type TestItem } from "@/lib/api";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [activeTest, setActiveTest] = useState<TestItem | null>(null);
  const [testDone, setTestDone] = useState(false);
  const [testPassed, setTestPassed] = useState(false);

  // Redirect if not authenticated
  if (!authLoading && !user) {
    router.push("/login");
    return null;
  }

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    setActiveTest(null);
    setTestDone(false);

    try {
      const test = await createTest(url);
      setActiveTest(test);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create test");
    } finally {
      setSubmitting(false);
    }
  };

  const handleComplete = (passed: boolean) => {
    setTestDone(true);
    setTestPassed(passed);
  };

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* URL Input */}
      <form onSubmit={handleSubmit} className="mb-6">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            placeholder="https://example.com"
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={submitting || (!!activeTest && !testDone)}
            className="whitespace-nowrap rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Start Test"}
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Active Test Progress */}
      {activeTest && (
        <div className="mb-6">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm text-gray-600">
              Test #{activeTest.id} — {activeTest.target_url}
            </p>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                activeTest.status === "queued"
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

          <TestProgress testId={activeTest.id} onComplete={handleComplete} />

          {testDone && (
            <div className="mt-4 flex items-center gap-3">
              <span
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                  testPassed
                    ? "bg-green-100 text-green-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {testPassed ? "PASSED" : "FAILED"}
              </span>
              <button
                onClick={() => router.push(`/tests/${activeTest.id}`)}
                className="text-sm text-blue-600 hover:underline"
              >
                View details
              </button>
            </div>
          )}
        </div>
      )}

      {/* Quick links */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <p className="text-sm text-gray-600">
          View all your tests in the{" "}
          <button
            onClick={() => router.push("/tests")}
            className="text-blue-600 hover:underline"
          >
            Test History
          </button>
          .
        </p>
      </div>
    </div>
  );
}
