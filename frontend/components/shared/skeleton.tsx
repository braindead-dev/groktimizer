export function Skeleton({ width, height = 14 }: { width: string; height?: number }) {
  return <span className="skeleton-block" style={{ width, height }} aria-hidden />;
}

export function ChatSkeleton() {
  return (
    <div className="chat-skeleton" role="status" aria-label="Loading message history">
      <div className="chat-skeleton-user"><Skeleton width="42%" height={36} /></div>
      <div><Skeleton width="68%" height={52} /></div>
      <div className="chat-skeleton-user"><Skeleton width="30%" height={36} /></div>
      <div><Skeleton width="56%" height={40} /></div>
    </div>
  );
}
