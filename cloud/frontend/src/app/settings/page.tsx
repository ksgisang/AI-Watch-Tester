"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import Link from "next/link";
import {
  createApiKey,
  listApiKeys,
  deleteApiKey,
  fetchBilling,
  type ApiKeyItem,
  type ApiKeyCreatedItem,
  type BillingInfo,
} from "@/lib/api";

export default function SettingsPage() {
  const { user } = useAuth();
  const t = useTranslations("settings");

  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<ApiKeyCreatedItem | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [billing, setBilling] = useState<BillingInfo | null>(null);

  const loadKeys = async () => {
    try {
      const data = await listApiKeys();
      setKeys(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load keys");
    }
  };

  useEffect(() => {
    if (user) {
      loadKeys();
      fetchBilling().then(setBilling).catch(() => {});
    }
  }, [user]);

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    setLoading(true);
    setError("");
    try {
      const created = await createApiKey(newKeyName.trim());
      setCreatedKey(created);
      setNewKeyName("");
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create key");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async (key: string) => {
    await navigator.clipboard.writeText(key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevoke = async (id: number) => {
    if (!confirm(t("revokeConfirm"))) return;
    try {
      await deleteApiKey(id);
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke key");
    }
  };

  if (!user) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-gray-500">{t("loginRequired")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mb-8 text-sm text-gray-500">{t("subtitle")}</p>

      {/* API Keys Section */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="mb-1 text-lg font-semibold text-gray-900">
          {t("apiKeysTitle")}
        </h2>
        <p className="mb-4 text-sm text-gray-500">{t("apiKeysDesc")}</p>

        {billing?.tier === "free" ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-center">
            <p className="mb-3 text-sm text-amber-800">{t("apiKeysProOnly")}</p>
            <Link
              href="/pricing"
              className="inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              {t("upgradeToPro")}
            </Link>
          </div>
        ) : (
        <>
        {/* Create new key */}
        <div className="mb-4 flex gap-2">
          <input
            type="text"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder={t("keyNamePlaceholder")}
            className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <button
            onClick={handleCreate}
            disabled={loading || !newKeyName.trim()}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? t("generating") : t("generate")}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Newly created key (show once) */}
        {createdKey && (
          <div className="mb-4 rounded border border-green-200 bg-green-50 p-4">
            <p className="mb-2 text-sm font-medium text-green-800">
              {t("keyCreated")}
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-white px-3 py-2 font-mono text-sm text-gray-900 border border-green-200">
                {createdKey.key}
              </code>
              <button
                onClick={() => handleCopy(createdKey.key)}
                className="rounded bg-green-600 px-3 py-2 text-sm text-white hover:bg-green-700"
              >
                {copied ? t("copied") : t("copy")}
              </button>
            </div>
            <p className="mt-2 text-xs text-green-700">{t("keyWarning")}</p>
          </div>
        )}

        {/* Key list */}
        {keys.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            {t("noKeys")}
          </p>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between rounded border border-gray-200 px-4 py-3"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <code className="font-mono text-sm text-gray-600">
                      {k.prefix}...
                    </code>
                    <span className="text-sm text-gray-800">{k.name}</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-400">
                    {t("created")}{" "}
                    {new Date(k.created_at).toLocaleDateString()}
                    {k.last_used_at && (
                      <>
                        {" · "}
                        {t("lastUsed")}{" "}
                        {new Date(k.last_used_at).toLocaleDateString()}
                      </>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => handleRevoke(k.id)}
                  className="rounded px-3 py-1 text-sm text-red-600 hover:bg-red-50"
                >
                  {t("revoke")}
                </button>
              </div>
            ))}
          </div>
        )}
        </>
        )}
      </div>
    </div>
  );
}
