"use client";

import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";

export default function LanguageToggle() {
  const locale = useLocale();
  const router = useRouter();

  const toggle = () => {
    const next = locale === "ko" ? "en" : "ko";
    document.cookie = `NEXT_LOCALE=${next};path=/;max-age=31536000`;
    router.refresh();
  };

  return (
    <button
      onClick={toggle}
      className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
      title={locale === "ko" ? "Switch to English" : "\ud55c\uad6d\uc5b4\ub85c \uc804\ud658"}
    >
      {locale === "ko" ? "\ud83c\uddfa\ud83c\uddf8 EN" : "\ud83c\uddf0\ud83c\uddf7 KO"}
    </button>
  );
}
