import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import "./globals.css";
import { AuthProvider } from "@/components/AuthProvider";
import Header from "@/components/Header";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "AWT — AI-Powered E2E Testing",
    template: "%s | AWT",
  },
  description:
    "Just enter a URL. AI generates test scenarios, executes them with Playwright, and reports results. No code required.",
  keywords: [
    "AI testing",
    "E2E testing",
    "automated testing",
    "web testing",
    "Playwright",
    "DevQA",
    "test automation",
    "AI QA",
  ],
  metadataBase: new URL("https://awt.dev"),
  openGraph: {
    type: "website",
    siteName: "AWT",
    title: "AWT — AI-Powered E2E Testing",
    description:
      "Just enter a URL. AI generates test scenarios, executes them with Playwright, and reports results.",
    images: [{ url: "/og-image.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "AWT — AI-Powered E2E Testing",
    description:
      "Just enter a URL. AI generates test scenarios, executes them with Playwright, and reports results.",
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <NextIntlClientProvider messages={messages}>
          <AuthProvider>
            <Header />
            <main>{children}</main>
          </AuthProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
