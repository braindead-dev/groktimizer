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

export function SidebarTreeSkeleton() {
  return (
    <div className="sidebar-tree-skeleton" role="status" aria-label="Loading projects">
      <div className="sidebar-skeleton-row">
        <Skeleton width="14px" height={14} />
        <Skeleton width="58%" height={10} />
        <Skeleton width="7px" height={7} />
      </div>
      <div className="sidebar-skeleton-row sidebar-skeleton-row-nested">
        <Skeleton width="13px" height={13} />
        <Skeleton width="44%" height={9} />
        <Skeleton width="7px" height={7} />
      </div>
      <div className="sidebar-skeleton-row">
        <Skeleton width="14px" height={14} />
        <Skeleton width="48%" height={10} />
        <Skeleton width="7px" height={7} />
      </div>
    </div>
  );
}
