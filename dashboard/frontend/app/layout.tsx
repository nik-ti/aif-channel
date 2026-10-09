// Root layout: fonts, global styles, and the React Query provider every
// tab's polling hook depends on. Theme (light/dark) is applied by
// Header.tsx toggling a class on <html>, not here — light is the default.
import type { Metadata } from "next";
import { Sora } from "next/font/google";
import localFont from "next/font/local";

import "./globals.css";
import { Providers } from "./providers";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});
// Headings and big numbers: wide, geometric, a little technical.
const sora = Sora({ subsets: ["latin"], variable: "--font-sora", weight: ["500", "600", "700"] });
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "AI Flow Dashboard",
  description: "Live monitor over the AI Flow Telegram channel",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${sora.variable} antialiased text-ink-primary`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
