import Link from "next/link";
import { getTranslations } from "next-intl/server";
import HeroAnimation from "@/components/HeroAnimation";

/* ------------------------------------------------------------------ */
/* JSON-LD structured data                                             */
/* ------------------------------------------------------------------ */

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "AWT - AI Watch Tester",
  description:
    "AI-powered E2E testing tool. Just enter a URL \u2014 AI generates test scenarios, executes them with Playwright, and reports results. Connect GitHub for automatic code fixes.",
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Web, macOS, Linux, Windows",
  offers: [
    { "@type": "Offer", price: "0", priceCurrency: "USD", name: "Free" },
    { "@type": "Offer", price: "29", priceCurrency: "USD", name: "Pro" },
    { "@type": "Offer", price: "49", priceCurrency: "USD", name: "Pro+GitHub" },
  ],
};

/* ------------------------------------------------------------------ */
/* Pricing table data                                                  */
/* ------------------------------------------------------------------ */

type CellValue = true | false | string;

interface PricingRow {
  key: string;
  free: CellValue;
  pro: CellValue;
  proGithub: CellValue;
  local: CellValue;
}

const PRICING_ROWS: PricingRow[] = [
  { key: "featAiScenario", free: true, pro: true, proGithub: true, local: true },
  { key: "featAutoExplore", free: "val3Pages", pro: "valUnlimited", proGithub: "valUnlimited", local: "valUnlimited" },
  { key: "featScreenshot", free: true, pro: true, proGithub: true, local: true },
  { key: "featSecurity", free: false, pro: true, proGithub: true, local: true },
  { key: "featFixGuide", free: false, pro: true, proGithub: true, local: true },
  { key: "featCodeAnalysis", free: false, pro: false, proGithub: true, local: true },
  { key: "featAutoFix", free: false, pro: false, proGithub: true, local: true },
  { key: "featDebugLoop", free: false, pro: false, proGithub: true, local: true },
  { key: "featDbSecurity", free: false, pro: false, proGithub: true, local: true },
  { key: "featOffline", free: false, pro: false, proGithub: false, local: true },
  { key: "featNoDataTransfer", free: false, pro: false, proGithub: false, local: true },
  { key: "featMonthlyTests", free: "val5Tests", pro: "val100Tests", proGithub: "valUnlimited", local: "valUnlimited" },
];

/* ------------------------------------------------------------------ */
/* Page component                                                      */
/* ------------------------------------------------------------------ */

export default async function LandingPage() {
  const t = await getTranslations("landing");

  return (
    <div className="overflow-hidden">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* ============================================================ */}
      {/* HERO                                                          */}
      {/* ============================================================ */}
      <section className="relative bg-gradient-to-b from-blue-50 via-white to-white px-4 pb-20 pt-16">
        <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-12 lg:grid-cols-2">
          {/* Left: text */}
          <div className="text-center lg:text-left">
            <h1 className="mb-5 text-3xl font-extrabold leading-tight tracking-tight text-gray-900 sm:text-4xl lg:text-5xl">
              {t("heroTitle")}
            </h1>
            <p className="mx-auto mb-8 max-w-lg text-lg text-gray-600 lg:mx-0">
              {t("heroDesc")}
            </p>
            <div className="flex flex-col items-center gap-3 sm:flex-row lg:justify-start">
              <Link
                href="/signup"
                className="inline-block rounded-lg bg-blue-600 px-7 py-3 text-base font-semibold text-white shadow-lg shadow-blue-600/25 transition hover:bg-blue-700 hover:shadow-blue-600/40"
              >
                {t("heroCta1")}
              </Link>
              <Link
                href="/signup"
                className="inline-block rounded-lg border border-gray-300 bg-white px-7 py-3 text-base font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
              >
                {t("heroCta2")}
              </Link>
            </div>
          </div>

          {/* Right: animation */}
          <HeroAnimation />
        </div>
      </section>

      {/* ============================================================ */}
      {/* CLOUD MODE                                                    */}
      {/* ============================================================ */}
      <section className="bg-white px-4 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="mb-3 text-center text-2xl font-bold text-gray-900 sm:text-3xl">
            {"\u2601\ufe0f"} {t("cloudTitle")}
          </h2>

          <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
            {/* URL Only card */}
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md">
              <h3 className="mb-1 text-lg font-bold text-gray-900">
                {t("urlOnlyTitle")}
              </h3>
              <p className="mb-1 text-sm font-medium text-blue-600">
                {t("urlOnlySubtitle")}
              </p>
              <p className="mb-4 text-xs text-gray-500">
                {t("urlOnlyTarget")}
              </p>
              <ul className="space-y-2 text-sm text-gray-700">
                {(["urlOnlyFeat1", "urlOnlyFeat2", "urlOnlyFeat3", "urlOnlyFeat4", "urlOnlyFeat5", "urlOnlyFeat6"] as const).map(
                  (k) => (
                    <li key={k} className="flex items-start gap-2">
                      <span className="mt-0.5 text-blue-500">{"\u2713"}</span>
                      {t(k)}
                    </li>
                  ),
                )}
              </ul>
            </div>

            {/* GitHub card */}
            <div className="relative rounded-2xl border-2 border-blue-500 bg-blue-50/30 p-6 shadow-sm transition hover:shadow-md">
              <span className="absolute -top-3 right-4 rounded-full bg-blue-600 px-3 py-0.5 text-xs font-bold text-white shadow">
                {"\u2605"} {t("githubBadge")}
              </span>
              <h3 className="mb-1 text-lg font-bold text-gray-900">
                {t("githubTitle")}
              </h3>
              <p className="mb-1 text-sm font-medium text-blue-600">
                {t("githubSubtitle")}
              </p>
              <p className="mb-4 text-xs text-gray-500">
                {t("githubTarget")}
              </p>
              <ul className="space-y-2 text-sm text-gray-700">
                {(["githubFeat1", "githubFeat2", "githubFeat3", "githubFeat4", "githubFeat5", "githubFeat6"] as const).map(
                  (k) => (
                    <li key={k} className="flex items-start gap-2">
                      <span className="mt-0.5 text-blue-500">{"\u2713"}</span>
                      {t(k)}
                    </li>
                  ),
                )}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* LOCAL MODE                                                    */}
      {/* ============================================================ */}
      <section className="bg-gray-50 px-4 py-20">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-3 text-center text-2xl font-bold text-gray-900 sm:text-3xl">
            {"\ud83d\udcbb"} {t("localTitle")}
          </h2>
          <p className="mb-8 text-center text-sm text-gray-500">
            {t("localTarget")}
          </p>

          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm md:p-8">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <ul className="space-y-3 text-sm text-gray-700">
                {(["localFeat1", "localFeat2", "localFeat3", "localFeat4", "localFeat5"] as const).map(
                  (k) => (
                    <li key={k} className="flex items-start gap-2">
                      <span className="mt-0.5 text-green-500">{"\u2713"}</span>
                      {t(k)}
                    </li>
                  ),
                )}
              </ul>
              <div className="flex flex-col items-center justify-center rounded-xl bg-gray-900 p-6">
                <p className="mb-2 text-xs text-gray-400">{t("localCommandLabel")}</p>
                <code className="text-lg font-bold text-green-400">
                  {t("localCommand")}
                </code>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* PRICING TABLE                                                 */}
      {/* ============================================================ */}
      <section className="bg-white px-4 py-20">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-10 text-center text-2xl font-bold text-gray-900 sm:text-3xl">
            {t("pricingTitle")}
          </h2>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="px-4 py-3 text-left font-medium text-gray-500">
                    {t("feature")}
                  </th>
                  <th className="px-4 py-3 text-center font-semibold text-gray-700">
                    <div>{t("freeTier")}</div>
                    <div className="text-lg font-bold text-gray-900">{t("freePrice")}</div>
                  </th>
                  <th className="px-4 py-3 text-center font-semibold text-gray-700">
                    <div>{t("proTier")}</div>
                    <div className="text-lg font-bold text-gray-900">
                      {t("proPrice")}
                      <span className="text-xs font-normal text-gray-500">{t("perMonth")}</span>
                    </div>
                  </th>
                  <th className="relative rounded-t-xl bg-blue-50 px-4 py-3 text-center font-semibold text-blue-700 ring-2 ring-blue-500">
                    <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-blue-600 px-2.5 py-0.5 text-[10px] font-bold text-white whitespace-nowrap">
                      {t("mostPopular")}
                    </span>
                    <div>{t("proGithubTier")}</div>
                    <div className="text-lg font-bold text-blue-900">
                      {t("proGithubPrice")}
                      <span className="text-xs font-normal text-blue-600">{t("perMonth")}</span>
                    </div>
                  </th>
                  <th className="px-4 py-3 text-center font-semibold text-gray-700">
                    <div>{t("localTier")}</div>
                    <div className="text-lg font-bold text-gray-900">
                      {t("localPrice")}
                      <span className="text-xs font-normal text-gray-500">{t("perMonth")}</span>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {PRICING_ROWS.map((row) => (
                  <tr key={row.key} className="hover:bg-gray-50/50">
                    <td className="px-4 py-3 font-medium text-gray-700">{t(row.key)}</td>
                    {(["free", "pro", "proGithub", "local"] as const).map((tier) => {
                      const val = row[tier];
                      const isHighlighted = tier === "proGithub";
                      return (
                        <td
                          key={tier}
                          className={`px-4 py-3 text-center ${isHighlighted ? "bg-blue-50/50 ring-2 ring-inset ring-blue-500" : ""}`}
                        >
                          {val === true && <span className="text-green-500 font-bold">{"\u2713"}</span>}
                          {val === false && <span className="text-gray-300">{"\u2014"}</span>}
                          {typeof val === "string" && (
                            <span className="text-gray-700">{t(val)}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="px-4 py-4" />
                  <td className="px-4 py-4 text-center">
                    <Link
                      href="/signup"
                      className="inline-block rounded-lg border border-gray-300 px-4 py-2 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
                    >
                      {t("pricingCta")}
                    </Link>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <Link
                      href="/signup"
                      className="inline-block rounded-lg border border-blue-300 px-4 py-2 text-xs font-medium text-blue-700 transition hover:bg-blue-50"
                    >
                      {t("pricingCtaPro")}
                    </Link>
                  </td>
                  <td className="bg-blue-50/50 px-4 py-4 text-center ring-2 ring-inset ring-blue-500 rounded-b-xl">
                    <Link
                      href="/signup"
                      className="inline-block rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow transition hover:bg-blue-700"
                    >
                      {t("pricingCtaProGithub")}
                    </Link>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <a
                      href="https://github.com/ksgisang/AI-Watch-Tester#local-mode"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block rounded-lg border border-gray-300 px-4 py-2 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
                    >
                      {t("pricingCtaLocal")}
                    </a>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* USE CASES                                                     */}
      {/* ============================================================ */}
      <section className="bg-gray-50 px-4 py-20">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-10 text-center text-2xl font-bold text-gray-900 sm:text-3xl">
            {t("useCasesTitle")}
          </h2>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            {([
              { role: "useCase1Role", quote: "useCase1Quote", icon: "\ud83d\ude80" },
              { role: "useCase2Role", quote: "useCase2Quote", icon: "\ud83d\udcbb" },
              { role: "useCase3Role", quote: "useCase3Quote", icon: "\ud83d\udccb" },
              { role: "useCase4Role", quote: "useCase4Quote", icon: "\ud83c\udfe2" },
            ] as const).map((uc) => (
              <div
                key={uc.role}
                className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md"
              >
                <div className="mb-3 flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-xl">
                    {uc.icon}
                  </span>
                  <span className="text-sm font-bold text-gray-900">{t(uc.role)}</span>
                </div>
                <p className="text-sm leading-relaxed text-gray-600">
                  &ldquo;{t(uc.quote)}&rdquo;
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* GITHUB INTEGRATION                                            */}
      {/* ============================================================ */}
      <section className="bg-white px-4 py-20">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-10 text-center text-2xl font-bold text-gray-900 sm:text-3xl">
            {t("githubSetupTitle")}
          </h2>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
            {([
              { num: "1", title: "githubStep1Title", desc: "githubStep1Desc", icon: "\ud83d\udd11" },
              { num: "2", title: "githubStep2Title", desc: "githubStep2Desc", icon: "\ud83d\udcc2" },
              { num: "3", title: "githubStep3Title", desc: "githubStep3Desc", icon: "\ud83c\udf89" },
            ] as const).map((step) => (
              <div key={step.num} className="text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-100 text-2xl">
                  {step.icon}
                </div>
                <div className="mb-1 text-xs font-bold text-blue-600">Step {step.num}</div>
                <h3 className="mb-2 text-base font-bold text-gray-900">
                  {t(step.title)}
                </h3>
                <p className="text-sm text-gray-600">{t(step.desc)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* FOOTER CTA                                                    */}
      {/* ============================================================ */}
      <section className="bg-gradient-to-r from-blue-600 to-blue-700 px-4 py-16">
        <div className="mx-auto max-w-3xl text-center">
          <p className="mb-8 text-lg font-semibold text-white sm:text-xl">
            {t("footerCta")}
          </p>
          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Link
              href="/signup"
              className="inline-block rounded-lg bg-white px-7 py-3 text-base font-semibold text-blue-700 shadow transition hover:bg-blue-50"
            >
              {t("footerBtn1")}
            </Link>
            <Link
              href="/signup"
              className="inline-block rounded-lg border border-white/40 bg-white/10 px-7 py-3 text-base font-semibold text-white backdrop-blur transition hover:bg-white/20"
            >
              {t("footerBtn2")}
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
