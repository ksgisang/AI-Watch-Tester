import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pricing — AWT Cloud",
  description: "Choose the right plan for your AI testing needs. Free, Pro, and Team plans available.",
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
