import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GCC Job Market Intelligence",
  description: "AI-powered GCC labor market insights powered by Bayt.com data",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  );
}
