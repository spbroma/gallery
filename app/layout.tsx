import type { Metadata } from 'next';
import './globals.css';
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
export const metadata: Metadata = {
  title:"roma's photos",
  description:"roma's photos",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  openGraph: { title:"roma's photos", description:"roma's photos", images:[`${basePath}/og.webp`] },
  twitter: { card:'summary_large_image', title:"roma's photos", description:"roma's photos", images:[`${basePath}/og.webp`] },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
