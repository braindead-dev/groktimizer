import { AppShell } from "@/components/app-shell";
import { ResearchStoreProvider } from "@/store/research-store";

export default function Page() {
  return (
    <ResearchStoreProvider>
      <AppShell />
    </ResearchStoreProvider>
  );
}
