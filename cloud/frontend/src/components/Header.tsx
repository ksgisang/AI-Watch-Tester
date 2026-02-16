"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "./AuthProvider";

export default function Header() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const t = useTranslations("header");

  const handleSignOut = async () => {
    await signOut();
    router.push("/");
  };

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="text-xl font-bold text-gray-900">
          {t("brand")}
        </Link>

        <nav className="flex items-center gap-4">
          {user ? (
            <>
              <Link
                href="/dashboard"
                className="text-sm text-gray-600 hover:text-gray-900"
              >
                {t("dashboard")}
              </Link>
              <Link
                href="/tests"
                className="text-sm text-gray-600 hover:text-gray-900"
              >
                {t("history")}
              </Link>
              <Link
                href="/status"
                className="text-sm text-gray-600 hover:text-gray-900"
              >
                {t("status")}
              </Link>
              <span className="text-xs text-gray-400">{user.email}</span>
              <button
                onClick={handleSignOut}
                className="rounded bg-gray-100 px-3 py-1 text-sm text-gray-700 hover:bg-gray-200"
              >
                {t("signOut")}
              </button>
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="text-sm text-gray-600 hover:text-gray-900"
              >
                {t("login")}
              </Link>
              <Link
                href="/signup"
                className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
              >
                {t("signUp")}
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
