import React from "react";
import { Inter, JetBrains_Mono, Source_Code_Pro, VT323 } from "next/font/google";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { AppShell } from "@/components/shell/AppShell";
import { GlobalToastListener } from "@/components/toast/GlobalToastListener";
import { AuthProvider } from "@/lib/auth-context";
import "@/styles/globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
});

const matrixBody = Source_Code_Pro({
  subsets: ["latin"],
  variable: "--font-matrix-body",
});

const matrixDisplay = VT323({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-matrix-display",
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} ${matrixBody.variable} ${matrixDisplay.variable}`}
    >
      <body suppressHydrationWarning>
        <ErrorBoundary>
          <QueryProvider>
            <AuthProvider>
              <GlobalToastListener />
              <AppShell>{children}</AppShell>
            </AuthProvider>
          </QueryProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
