import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function LandingPage() {
  const t = await getTranslations("landing");

  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      {/* Hero */}
      <section className="mb-16 text-center">
        <h1 className="mb-4 text-4xl font-bold tracking-tight text-gray-900">
          {t("heroLine1")}
          <br />
          <span className="text-blue-600">{t("heroLine2")}</span>
        </h1>
        <p className="mx-auto mb-8 max-w-xl text-lg text-gray-600">
          {t("heroDescription")}
        </p>
        <Link
          href="/signup"
          className="inline-block rounded-lg bg-blue-600 px-8 py-3 text-lg font-medium text-white hover:bg-blue-700"
        >
          {t("heroCta")}
        </Link>
      </section>

      {/* How it works */}
      <section className="mb-16">
        <h2 className="mb-8 text-center text-2xl font-bold text-gray-900">
          {t("howItWorks")}
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {[
            {
              step: "1",
              title: t("step1Title"),
              desc: t("step1Desc"),
            },
            {
              step: "2",
              title: t("step2Title"),
              desc: t("step2Desc"),
            },
            {
              step: "3",
              title: t("step3Title"),
              desc: t("step3Desc"),
            },
          ].map((item) => (
            <div
              key={item.step}
              className="rounded-lg border border-gray-200 p-6 text-center"
            >
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-blue-100 text-lg font-bold text-blue-600">
                {item.step}
              </div>
              <h3 className="mb-2 font-semibold text-gray-900">{item.title}</h3>
              <p className="text-sm text-gray-600">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Cloud vs Local */}
      <section className="mb-16">
        <h2 className="mb-8 text-center text-2xl font-bold text-gray-900">
          {t("comparisonHeading")}
        </h2>
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-3 font-medium text-gray-500"></th>
                <th className="px-4 py-3 font-semibold text-blue-600">Cloud</th>
                <th className="px-4 py-3 font-semibold text-gray-900">Local (CLI)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <tr>
                <td className="px-4 py-3 font-medium text-gray-700">{t("compInstall")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compCloudInstall")}</td>
                <td className="px-4 py-3 text-gray-600">
                  <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">{t("compLocalInstall")}</code>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-gray-700">{t("compRun")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compCloudRun")}</td>
                <td className="px-4 py-3 text-gray-600">
                  <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">{t("compLocalRun")}</code>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-gray-700">{t("compObserve")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compCloudObserve")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compLocalObserve")}</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-gray-700">{t("compBestFor")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compCloudBestFor")}</td>
                <td className="px-4 py-3 text-gray-600">{t("compLocalBestFor")}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-center text-sm text-gray-500">
          {t("compFooter")}{" "}
          <a
            href="https://github.com/ksgisang/AI-Watch-Tester#local-mode"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            {t("compLocalGuide")}
          </a>
        </p>
      </section>

      {/* Pricing */}
      <section>
        <h2 className="mb-8 text-center text-2xl font-bold text-gray-900">
          {t("pricingHeading")}
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Free */}
          <div className="rounded-lg border border-gray-200 p-6">
            <h3 className="mb-2 text-xl font-bold text-gray-900">{t("freeName")}</h3>
            <p className="mb-4 text-3xl font-bold text-gray-900">
              {t("freePrice")}<span className="text-sm font-normal text-gray-500">{t("perMonth")}</span>
            </p>
            <ul className="mb-6 space-y-2 text-sm text-gray-600">
              <li>&#10003; {t("freeFeat1")}</li>
              <li>&#10003; {t("freeFeat2")}</li>
              <li>&#10003; {t("freeFeat3")}</li>
              <li>&#10003; {t("freeFeat4")}</li>
            </ul>
            <Link
              href="/signup"
              className="block rounded-lg border border-gray-300 py-2 text-center text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("freeCta")}
            </Link>
          </div>

          {/* Pro */}
          <div className="rounded-lg border-2 border-blue-500 p-6">
            <h3 className="mb-2 text-xl font-bold text-gray-900">{t("proName")}</h3>
            <p className="mb-4 text-3xl font-bold text-gray-900">
              {t("proPrice")}<span className="text-sm font-normal text-gray-500">{t("perMonth")}</span>
            </p>
            <ul className="mb-6 space-y-2 text-sm text-gray-600">
              <li>&#10003; {t("proFeat1")}</li>
              <li>&#10003; {t("proFeat2")}</li>
              <li>&#10003; {t("proFeat3")}</li>
              <li>&#10003; {t("proFeat4")}</li>
            </ul>
            <Link
              href="/signup"
              className="block rounded-lg bg-blue-600 py-2 text-center text-sm font-medium text-white hover:bg-blue-700"
            >
              {t("proCta")}
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
