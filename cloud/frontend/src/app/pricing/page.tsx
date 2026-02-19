"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/AuthProvider";
import { getCheckoutUrl } from "@/lib/api";

export default function PricingPage() {
  const t = useTranslations("pricing");
  const { user } = useAuth();

  const plans = [
    {
      key: "free",
      name: t("free"),
      price: t("freePrice"),
      desc: t("freeDesc"),
      features: [t("freeFeat1"), t("freeFeat2"), t("freeFeat3"), t("freeFeat4")],
      cta: t("freeCta"),
      href: user ? "/dashboard" : "/signup",
      highlighted: false,
    },
    {
      key: "pro",
      name: t("pro"),
      price: t("proPrice"),
      desc: t("proDesc"),
      features: [t("proFeat1"), t("proFeat2"), t("proFeat3"), t("proFeat4"), t("proFeat5")],
      cta: t("proCta"),
      href: user ? getCheckoutUrl("pro", user.id) : "/signup",
      highlighted: true,
    },
    {
      key: "team",
      name: t("team"),
      price: t("teamPrice"),
      desc: t("teamDesc"),
      features: [t("teamFeat1"), t("teamFeat2"), t("teamFeat3"), t("teamFeat4")],
      cta: t("teamCta"),
      href: user ? getCheckoutUrl("team", user.id) : "/signup",
      highlighted: false,
    },
  ];

  return (
    <div className="mx-auto max-w-5xl px-4 py-16">
      <div className="mb-12 text-center">
        <h1 className="mb-3 text-3xl font-bold text-gray-900 sm:text-4xl">
          {t("title")}
        </h1>
        <p className="text-lg text-gray-600">{t("subtitle")}</p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {plans.map((plan) => (
          <div
            key={plan.key}
            className={`relative flex flex-col rounded-2xl border p-6 shadow-sm transition hover:shadow-md ${
              plan.highlighted
                ? "border-2 border-blue-500 bg-blue-50/30"
                : "border-gray-200 bg-white"
            }`}
          >
            {plan.highlighted && (
              <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-blue-600 px-3 py-0.5 text-xs font-bold text-white">
                {t("mostPopular")}
              </span>
            )}

            <h2 className="mb-1 text-xl font-bold text-gray-900">{plan.name}</h2>
            <div className="mb-2">
              <span className="text-3xl font-bold text-gray-900">{plan.price}</span>
              {plan.key !== "free" && (
                <span className="text-sm text-gray-500">{t("perMonth")}</span>
              )}
            </div>
            <p className="mb-6 text-sm text-gray-600">{plan.desc}</p>

            <ul className="mb-8 flex-1 space-y-3">
              {plan.features.map((feat, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="mt-0.5 text-green-500">{"\u2713"}</span>
                  {feat}
                </li>
              ))}
            </ul>

            {plan.href.startsWith("http") ? (
              <a
                href={plan.href}
                className={`block rounded-lg px-4 py-2.5 text-center text-sm font-medium transition ${
                  plan.highlighted
                    ? "bg-blue-600 text-white hover:bg-blue-700"
                    : "border border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                {plan.cta}
              </a>
            ) : (
              <Link
                href={plan.href}
                className={`block rounded-lg px-4 py-2.5 text-center text-sm font-medium transition ${
                  plan.highlighted
                    ? "bg-blue-600 text-white hover:bg-blue-700"
                    : "border border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                {plan.cta}
              </Link>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
