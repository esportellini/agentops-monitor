import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/layout/Providers";
export const metadata: Metadata = { title: { default: "AgentOps Monitor", template: "%s · AgentOps Monitor" }, description: "Operations, governance, security and evaluation for AI agents" };
export const viewport: Viewport = { colorScheme: "dark", themeColor: "#0b0d10" };
export default function RootLayout({ children }: { children: React.ReactNode }) { return <html lang="en"><body><Providers>{children}</Providers></body></html>; }
