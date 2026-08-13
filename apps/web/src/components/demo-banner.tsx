/**
 * States, on every screen, that the deployment has no authentication.
 *
 * The public demo trusts the X-User-Role header from the browser, so anyone
 * with the URL is an attorney. That is an accepted tradeoff for a throwaway
 * demo and an unacceptable thing to leave unsaid — a reviewer looking at a
 * page full of medical records is entitled to know it is not protected.
 *
 * Rendered only when NEXT_PUBLIC_DEMO_BANNER is set, so local development and
 * any properly authenticated deployment show nothing.
 */
export function DemoBanner() {
  if (process.env.NEXT_PUBLIC_DEMO_BANNER !== "1") return null;

  return (
    <div
      role="alert"
      data-testid="demo-banner"
      className="flex flex-wrap items-baseline justify-center gap-x-2 gap-y-0.5 border-b border-warn-200 bg-warn-50 px-4 py-1.5 text-center"
    >
      <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-warn-800">
        Public demo — no authentication
      </span>
      <span className="text-2xs text-warn-700">
        Anyone with this URL has attorney permissions. Upload synthetic case material only;
        never real client or medical records. Data is erased on every redeploy.
      </span>
    </div>
  );
}
