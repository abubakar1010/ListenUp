import { usePageTitle } from './usePageTitle';

/** Route-table helper for pages that do not set their own title. */
export function PageTitle({ title }: { title: string }) {
  usePageTitle(title);
  return null;
}
