"use client";

import BackgroundPaths from "@/components/modern-background-paths";

type HeroBackgroundProps = {
  variant?: "light" | "dark";
};

export default function HeroBackground({
  variant = "light",
}: HeroBackgroundProps) {
  return <BackgroundPaths variant={variant} />;
}