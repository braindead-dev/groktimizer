import { useId } from "react";

function GrokMark() {
  const maskId = useId();
  return (
    <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
        <rect width="64" height="64" fill="white" />
        <path d="M5 59 59 5" stroke="black" strokeWidth="11" />
      </mask>
      <circle cx="32" cy="32" r="19" stroke="currentColor" strokeWidth="8" mask={`url(#${maskId})`} />
      <path d="M5 59 59 5" stroke="currentColor" strokeWidth="6" />
    </svg>
  );
}

export function BrandMark() {
  return <span className="brand-mark"><GrokMark /></span>;
}

export function BrandLockup() {
  return (
    <div className="brand-lockup" aria-label="Groktimizer">
      <BrandMark />
      <span>Groktimizer</span>
    </div>
  );
}
