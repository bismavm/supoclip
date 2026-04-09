"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { ArrowRight, Play, ShieldCheck, Sparkles, Workflow, Gauge, Scissors, Type, MonitorSmartphone, CheckCircle2, ChevronDown, Menu, X } from "lucide-react";
import { isLandingOnlyModeEnabled } from "@/lib/app-flags";

function ScrollReveal({
  children,
  className = "",
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -64px 0px" }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(22px)",
        transition: `opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1) ${delay}s, transform 0.8s cubic-bezier(0.16, 1, 0.3, 1) ${delay}s`,
      }}
    >
      {children}
    </div>
  );
}

const KPIS = [
  { value: "3x", label: "Faster short-video output" },
  { value: "98%", label: "Subtitle timing consistency" },
  { value: "24/7", label: "Automated clipping pipeline" },
  { value: "9:16", label: "Vertical-ready every generation" },
];

const CAPABILITIES = [
  {
    icon: Scissors,
    title: "AI Segment Intelligence",
    description:
      "Detects high-retention moments from long-form content and suggests clips built for short-feed performance.",
  },
  {
    icon: Type,
    title: "Studio-Grade Subtitles",
    description:
      "Word-synced subtitle rendering with polished typography presets and precise animation timing.",
  },
  {
    icon: MonitorSmartphone,
    title: "Platform-Ready Outputs",
    description:
      "Generate exports tuned for Shorts, Reels, and TikTok with vertical framing and clear pacing.",
  },
  {
    icon: Gauge,
    title: "Performance Scoring",
    description:
      "Each clip is scored for hook potential and engagement quality so teams can prioritize what to publish.",
  },
];

const PROCESS = [
  {
    step: "01",
    title: "Ingest",
    detail: "Upload media or provide a link. AI Shorts Gen reads structure, speech, and pacing in minutes.",
  },
  {
    step: "02",
    title: "Refine",
    detail: "Review recommended segments, subtitle style, and output format inside a guided editing flow.",
  },
  {
    step: "03",
    title: "Publish",
    detail: "Export polished clips optimized for modern short-video platforms and iterate from performance insights.",
  },
];

export default function LandingPage() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const authEnabled = !isLandingOnlyModeEnabled;

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background text-foreground">
      <div className="pointer-events-none absolute inset-0 devoteam-grid opacity-60" />
      <div className="pointer-events-none absolute inset-0 soft-radial-glow" />

      <nav
        className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
          scrolled
            ? "border-b border-[#e8dedd] bg-[#fffdfd]/95 backdrop-blur"
            : "bg-transparent"
        }`}
      >
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-5 md:px-8">
          <Link href="/" className="flex items-center gap-2.5">
            <Image src="/logo.png" alt="AI Shorts Gen" width={28} height={28} className="rounded-md" />
            <span className="font-[family-name:var(--font-editorial)] text-xl tracking-tight">AI Shorts Gen</span>
          </Link>

          <div className="hidden items-center gap-8 md:flex">
            <a href="#capabilities" className="text-sm text-[#4a3431] transition-colors hover:text-[#b63a3f]">Capabilities</a>
            <a href="#workflow" className="text-sm text-[#4a3431] transition-colors hover:text-[#b63a3f]">Workflow</a>
            <a href="#results" className="text-sm text-[#4a3431] transition-colors hover:text-[#b63a3f]">Results</a>
          </div>

          <div className="hidden items-center gap-2 md:flex">
            {authEnabled ? (
              <>
                <Link href="/sign-in">
                  <Button variant="ghost" className="text-[#4a3431] hover:bg-[#f6eceb] hover:text-[#9d2f34]">Sign In</Button>
                </Link>
                <Link href="/sign-up">
                  <Button className="bg-[#b63a3f] text-white hover:bg-[#9f2f34]">Start Creating</Button>
                </Link>
              </>
            ) : (
              <a href="#results">
                <Button className="bg-[#b63a3f] text-white hover:bg-[#9f2f34]">Explore Results</Button>
              </a>
            )}
          </div>

          <button
            aria-label="Toggle menu"
            className="rounded-md p-2 text-[#472f2d] transition hover:bg-[#f6eceb] md:hidden"
            onClick={() => setMobileNavOpen((prev) => !prev)}
            type="button"
          >
            {mobileNavOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>

        {mobileNavOpen && (
          <div className="border-t border-[#e8dedd] bg-[#fffdfd] p-4 md:hidden">
            <div className="flex flex-col gap-3">
              <a href="#capabilities" className="text-sm text-[#4a3431]">Capabilities</a>
              <a href="#workflow" className="text-sm text-[#4a3431]">Workflow</a>
              <a href="#results" className="text-sm text-[#4a3431]">Results</a>
              {authEnabled ? (
                <div className="mt-2 flex gap-2">
                  <Link href="/sign-in" className="flex-1">
                    <Button variant="outline" className="w-full border-[#dfc7c5] text-[#4a3431]">Sign In</Button>
                  </Link>
                  <Link href="/sign-up" className="flex-1">
                    <Button className="w-full bg-[#b63a3f] text-white hover:bg-[#9f2f34]">Start</Button>
                  </Link>
                </div>
              ) : null}
            </div>
          </div>
        )}
      </nav>

      <main className="relative z-10 pt-28 md:pt-32">
        <section className="mx-auto max-w-7xl px-5 pb-20 md:px-8 md:pb-24">
          <ScrollReveal>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#efdbd9] bg-[#fff3f2] px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#a53439]">
              <Sparkles className="h-3.5 w-3.5" />
              AI Video Short Generation Platform
            </div>
          </ScrollReveal>

          <ScrollReveal className="mt-6" delay={0.04}>
            <h1 className="max-w-5xl font-[family-name:var(--font-editorial)] text-4xl leading-[1.05] tracking-tight text-[#211716] sm:text-5xl md:text-7xl">
              Turn long-form content into
              <span className="text-[#b63a3f]"> high-performing short videos</span> at enterprise speed.
            </h1>
          </ScrollReveal>

          <ScrollReveal className="mt-6" delay={0.08}>
            <p className="max-w-2xl text-base leading-relaxed text-[#5a4442] md:text-lg">
              AI Shorts Gen helps teams detect winning moments, craft refined subtitles, and ship platform-ready clips with a white-first workflow built for consistency.
            </p>
          </ScrollReveal>

          <ScrollReveal className="mt-8 flex flex-wrap items-center gap-3" delay={0.12}>
            {authEnabled ? (
              <Link href="/sign-up">
                <Button className="h-11 bg-[#b63a3f] px-6 text-white hover:bg-[#9f2f34]">
                  Start With AI Shorts Gen
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
            ) : (
              <a href="#workflow">
                <Button className="h-11 bg-[#b63a3f] px-6 text-white hover:bg-[#9f2f34]">
                  Explore Workflow
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
            )}
            <a href="#workflow">
              <Button variant="outline" className="h-11 border-[#e2cbca] bg-white px-6 text-[#412c2a] hover:bg-[#fdf2f1]">
                <Play className="mr-2 h-4 w-4" />
                See How It Works
              </Button>
            </a>
          </ScrollReveal>
        </section>

        <section id="results" className="border-y border-[#ebdedd] bg-[#fff8f7]">
          <div className="mx-auto grid max-w-7xl gap-4 px-5 py-9 sm:grid-cols-2 md:grid-cols-4 md:px-8">
            {KPIS.map((kpi, index) => (
              <ScrollReveal key={kpi.label} delay={index * 0.05}>
                <div className="rounded-xl border border-[#ecd6d4] bg-white p-5">
                  <p className="font-[family-name:var(--font-editorial)] text-4xl leading-none text-[#9f2f34]">{kpi.value}</p>
                  <p className="mt-2 text-sm text-[#5b4341]">{kpi.label}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </section>

        <section id="capabilities" className="mx-auto max-w-7xl px-5 py-16 md:px-8 md:py-24">
          <ScrollReveal>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#a3363a]">
              <ShieldCheck className="h-4 w-4" />
              Core Capabilities
            </div>
            <h2 className="mt-3 max-w-3xl font-[family-name:var(--font-editorial)] text-3xl leading-tight text-[#231816] md:text-5xl">
              A production workflow designed for creative teams that move fast.
            </h2>
          </ScrollReveal>

          <div className="mt-10 grid gap-5 md:grid-cols-2">
            {CAPABILITIES.map((item, index) => {
              const Icon = item.icon;
              return (
                <ScrollReveal key={item.title} delay={index * 0.06}>
                  <article className="group h-full rounded-2xl border border-[#ead4d2] bg-white p-6 transition-colors hover:border-[#d9b2af]">
                    <div className="mb-4 inline-flex rounded-lg border border-[#f0dddb] bg-[#fff6f5] p-2.5 text-[#a4363b]">
                      <Icon className="h-5 w-5" />
                    </div>
                    <h3 className="font-[family-name:var(--font-editorial)] text-2xl text-[#241918]">{item.title}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-[#5a4341]">{item.description}</p>
                  </article>
                </ScrollReveal>
              );
            })}
          </div>
        </section>

        <section id="workflow" className="border-y border-[#ebdddd] bg-[#fff9f8]">
          <div className="mx-auto max-w-7xl px-5 py-16 md:px-8 md:py-24">
            <ScrollReveal>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#a3363a]">
                <Workflow className="h-4 w-4" />
                Workflow
              </div>
              <h2 className="mt-3 max-w-3xl font-[family-name:var(--font-editorial)] text-3xl leading-tight text-[#231816] md:text-5xl">
                From raw footage to publish-ready shorts in three deliberate steps.
              </h2>
            </ScrollReveal>

            <div className="relative mt-10 space-y-5">
              <div className="absolute left-[21px] top-0 hidden h-full w-px bg-[#e4c9c7] md:block" />
              {PROCESS.map((item, index) => (
                <ScrollReveal key={item.step} delay={index * 0.08}>
                  <article className="relative rounded-2xl border border-[#ead4d2] bg-white p-6 md:pl-16">
                    <span className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full border border-[#e8c9c6] bg-[#fff0ee] font-semibold text-[#a53439] md:absolute md:left-4 md:top-6">
                      {item.step}
                    </span>
                    <h3 className="font-[family-name:var(--font-editorial)] text-2xl text-[#241918]">{item.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-[#5a4341]">{item.detail}</p>
                  </article>
                </ScrollReveal>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 md:px-8 md:py-24">
          <ScrollReveal>
            <div className="rounded-3xl border border-[#e5c5c2] bg-white p-8 md:p-12">
              <div className="max-w-3xl">
                <p className="inline-flex items-center gap-2 rounded-full bg-[#fff1ef] px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-[#a3363a]">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Ready To Launch
                </p>
                <h2 className="mt-4 font-[family-name:var(--font-editorial)] text-3xl leading-tight text-[#241918] md:text-5xl">
                  Build a repeatable short-video engine with AI Shorts Gen.
                </h2>
                <p className="mt-4 text-sm leading-relaxed text-[#5a4341] md:text-base">
                  Replace fragmented clipping workflows with one cohesive system for detection, subtitle polish, and export consistency.
                </p>
              </div>

              <div className="mt-7 flex flex-wrap gap-3">
                {authEnabled ? (
                  <>
                    <Link href="/sign-up">
                      <Button className="h-11 bg-[#b63a3f] px-6 text-white hover:bg-[#9f2f34]">
                        Create Your First Short
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Button>
                    </Link>
                    <Link href="/sign-in">
                      <Button variant="outline" className="h-11 border-[#dcc3c1] px-6 text-[#412c2a] hover:bg-[#fff3f1]">
                        Sign In
                      </Button>
                    </Link>
                  </>
                ) : (
                  <a href="#capabilities">
                    <Button className="h-11 bg-[#b63a3f] px-6 text-white hover:bg-[#9f2f34]">
                      Review Capabilities
                      <ChevronDown className="ml-2 h-4 w-4" />
                    </Button>
                  </a>
                )}
              </div>
            </div>
          </ScrollReveal>
        </section>
      </main>
    </div>
  );
}
