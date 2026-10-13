"use client";

import { Activity, Calculator, CalendarDays, FlaskConical, HeartPulse, Trophy } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarHeader, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";

const NAV = [
  { href: "/", label: "Today", icon: CalendarDays },
  { href: "/teams/", label: "Teams", icon: Trophy },
  { href: "/performance/", label: "Performance", icon: Activity },
  { href: "/backtests/", label: "Backtests", icon: FlaskConical },
  { href: "/injuries/", label: "Injuries", icon: HeartPulse },
  { href: "/edge/", label: "Edge", icon: Calculator },
];

export function AppSidebar() {
  const pathname = usePathname();
  // The game page belongs to Today
  const active = (href: string) =>
    href === "/" ? pathname === "/" || pathname.startsWith("/game") : pathname.startsWith(href);
  return (
    <Sidebar>
      <SidebarHeader className="px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight">Avaris</Link>
        <p className="text-xs text-muted-foreground">NBA analytics model</p>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(({ href, label, icon: Icon }) => (
                <SidebarMenuItem key={href}>
                  <SidebarMenuButton asChild isActive={active(href)}>
                    <Link href={href}>
                      <Icon />
                      <span>{label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
