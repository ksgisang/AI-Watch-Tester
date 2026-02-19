import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Billing — AWT Cloud",
  description: "Manage your subscription and view usage.",
};

export default function BillingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
