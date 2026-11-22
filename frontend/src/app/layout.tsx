import type { Metadata } from "next";

import { Providers } from "./providers";
import "./globals.css";


export const metadata: Metadata = {
  title: "Similia AI",
  description: "AI-Powered Homeopathic Knowledge & Case Analysis Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
