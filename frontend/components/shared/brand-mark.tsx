import Image from "next/image";

export function BrandMark() {
  return (
    <span className="brand-mark">
      <Image src="/brand/grok-mark.png" alt="" width={104} height={112} />
    </span>
  );
}

export function BrandLockup() {
  return (
    <div className="brand-lockup" aria-label="Groktimizer">
      <Image
        className="brand-wordmark-image"
        src="/brand/grok-wordmark.png"
        alt=""
        width={302}
        height={112}
        priority
      />
      <span>timizer</span>
    </div>
  );
}
