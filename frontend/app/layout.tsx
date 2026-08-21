import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  title: 'SentinelLoop — Authorized Security Validation',
  description: 'Hypothesis-driven, evidence-backed AI security investigation for controlled environments.',
  openGraph: {
    title: 'SentinelLoop — Authorized Security Validation',
    description: 'Evidence first. Conclusions last.',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'SentinelLoop investigation loop' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'SentinelLoop — Authorized Security Validation',
    description: 'Evidence first. Conclusions last.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
