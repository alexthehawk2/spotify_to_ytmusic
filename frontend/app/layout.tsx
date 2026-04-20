import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spotify to YT Music",
  description: "Migrate your Spotify playlists to YouTube Music",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased bg-slate-950 text-slate-50 min-h-screen">
        {children}
      </body>
    </html>
  );
}
