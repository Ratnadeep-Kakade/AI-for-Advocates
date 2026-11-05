import DeadlineList from "../components/DeadlineList";
import { PageHeader } from "../components/ui";

export default function DeadlinesPage() {
  return (
    <>
      <PageHeader title="Deadlines" sub="Hearings, filings and limitation periods across all cases" />
      <div className="flex-1 overflow-y-auto"><div className="mx-auto max-w-3xl px-4 py-6"><DeadlineList /></div></div>
    </>
  );
}
