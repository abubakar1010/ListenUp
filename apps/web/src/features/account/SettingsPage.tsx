import { usePageTitle } from '../../app/usePageTitle';
import { DataExportSection } from './DataExportSection';

const PAGE_CLASS =
  'mx-auto flex w-full max-w-content flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12 xl:px-8';

/** Account settings (`/settings`). Each section is its own self-contained component. */
export default function SettingsPage() {
  usePageTitle('Settings');
  return (
    <main className={PAGE_CLASS}>
      <h1 className="font-display text-title-compact md:text-title">Settings</h1>
      <DataExportSection />
    </main>
  );
}
