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
      <body>
        <nav className="workspaceNav" aria-label="FulfillOS workspace">
          <a className="workspaceBrand" href="/">FulfillOS <span>v0.5</span></a>
          <div className="workspaceLinks">
            <a href="/">Overview</a>
            <a href="/operations#dispatch">Dispatch</a>
            <a href="/operations#orders">Orders</a>
            <a href="/operations#availability">Availability</a>
            <a href="/operations#replenishment">Replenishment</a>
            <a href="/operations#inbound">Inbound</a>
            <a href="/people#team">People</a>
            <a href="/people#schedule">Schedule</a>
            <a href="/people#payroll">Payroll</a>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
