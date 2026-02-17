import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Test Results",
};

export default function TestsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
