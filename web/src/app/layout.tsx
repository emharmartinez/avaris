import type { Metadata, Viewport } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { Providers } from "@/components/providers";
import { RefreshButton } from "@/components/refresh-button";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Avaris",
  description: "Personal NBA analytics model: win probability, margin and total",
  applicationName: "Avaris",
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <Providers>
          <SidebarProvider>
            <AppSidebar />
            {/* min-w-0: a wide table scrolls inside its card, not the whole page */}
            <SidebarInset className="min-w-0">
              <header className="flex h-14 items-center justify-between gap-4 border-b px-4">
                <SidebarTrigger />
                <RefreshButton />
              </header>
              <main className="flex-1 p-6">{children}</main>
            </SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  );
}
