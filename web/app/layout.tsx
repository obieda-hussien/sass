import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FulfillOS Control Tower",
  description: "Micro-fulfillment operations control tower",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
