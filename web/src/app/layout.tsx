import type { Metadata, Viewport } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { Providers } from "@/components/providers";
import { RefreshButton } from "@/components/refresh-button";
import { StopServerButton } from "@/components/stop-server-button";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Avaris",
  description: "Personal NBA analytics model: win probability, margin and total",
  applicationName: "Avaris",
};

// Dark only: the background is oklch(0.145 0 0), about #0a0a0a
export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="dark h-full antialiased">
      <body className="min-h-full">
        <Providers>
          <SidebarProvider>
            <AppSidebar />
            {/* min-w-0: a wide table scrolls inside its card, not the whole page */}
            <SidebarInset className="min-w-0">
              <header className="flex h-14 items-center justify-between gap-4 border-b px-4">
                <SidebarTrigger />
                <div className="flex min-w-0 items-center gap-2">
                  <RefreshButton />
                  <StopServerButton />
                </div>
              </header>
              <main className="flex-1 p-6">{children}</main>
            </SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  );
}
