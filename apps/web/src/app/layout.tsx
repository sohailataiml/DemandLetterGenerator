import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "./providers";
import { DemoBanner } from "@/components/demo-banner";

export const metadata: Metadata = {
  title: "Demand Letter Review",
  description:
    "Attorney review workspace for personal injury demand letters assembled from verified facts.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <DemoBanner />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
