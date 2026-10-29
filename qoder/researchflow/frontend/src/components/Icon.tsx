import type { ReactElement, SVGProps } from 'react'

/** 全站统一线性图标：24 网格、1.6 描边、继承 currentColor，避免混用多套图标。 */

const PATHS: Record<string, ReactElement> = {
  chat: (
    <>
      <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.3c-1.3 0-2.6-.3-3.7-.9L3.5 20l1.2-4.2a8.1 8.1 0 0 1-1.2-4.3A8.4 8.4 0 0 1 12 3.2a8.4 8.4 0 0 1 9 8.3Z" />
      <path d="M8.6 11.3h6.8M8.6 14.2h4.2" />
    </>
  ),
  book: (
    <>
      <path d="M4.5 4.2A1.7 1.7 0 0 1 6.2 2.5H19v17H6.2a1.7 1.7 0 0 0-1.7 1.7Z" />
      <path d="M4.5 19.2a1.7 1.7 0 0 1 1.7-1.7H19" />
      <path d="M8.4 7.2h6.6M8.4 10.2h4.6" />
    </>
  ),
  brain: (
    <>
      <path d="M9.5 3.6A2.6 2.6 0 0 0 6.4 6a2.5 2.5 0 0 0-1.6 4 2.6 2.6 0 0 0 .7 4.4A2.5 2.5 0 0 0 9.6 18c.6 0 1-.5 1-1.1V4.7c0-.6-.5-1.1-1.1-1.1Z" />
      <path d="M14.5 3.6A2.6 2.6 0 0 1 17.6 6a2.5 2.5 0 0 1 1.6 4 2.6 2.6 0 0 1-.7 4.4A2.5 2.5 0 0 1 14.4 18c-.6 0-1-.5-1-1.1V4.7c0-.6.5-1.1 1.1-1.1Z" />
      <path d="M9 21h6" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2.8 5 5.4v5.3c0 4.3 2.9 8.2 7 9.4 4.1-1.2 7-5.1 7-9.4V5.4Z" />
      <path d="m8.9 11.9 2.1 2.1 4.1-4.2" />
    </>
  ),
  docs: (
    <>
      <path d="M13.6 2.8H7a2 2 0 0 0-2 2v14.4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.2Z" />
      <path d="M13.6 2.8v5.4H19" />
      <path d="M8.6 13.2h6.8M8.6 16.4h4.4" />
    </>
  ),
  plus: <path d="M12 5.2v13.6M5.2 12h13.6" />,
  send: <path d="M12 19V5.4m0 0-5.6 5.6M12 5.4l5.6 5.6" />,
  upload: (
    <>
      <path d="M12 16V4.4m0 0L7.4 9M12 4.4 16.6 9" />
      <path d="M4.4 15v3.2a2 2 0 0 0 2 2h11.2a2 2 0 0 0 2-2V15" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.4" />
      <path d="m20 20-3.6-3.6" />
    </>
  ),
  close: <path d="M6 6 18 18M18 6 6 18" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4.1" />
      <path d="M12 2.6v2.2M12 19.2v2.2M4.4 4.4 6 6M18 18l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.4 19.6 6 18M18 6l1.6-1.6" />
    </>
  ),
  moon: <path d="M20.4 14.6A8.6 8.6 0 0 1 9.4 3.6a8.6 8.6 0 1 0 11 11Z" />,
  panelRight: (
    <>
      <rect x="3.2" y="4.4" width="17.6" height="15.2" rx="2" />
      <path d="M14.8 4.4v15.2" />
    </>
  ),
  chevronLeft: <path d="m14.5 5.5-7 6.5 7 6.5" />,
  chevronRight: <path d="m9.5 5.5 7 6.5-7 6.5" />,
  chevronDown: <path d="m5.5 9.5 6.5 7 6.5-7" />,
  check: <path d="m4.8 12.6 4.6 4.6L19.2 7" />,
  alert: (
    <>
      <path d="M12 8.4v5" />
      <circle cx="12" cy="16.6" r=".9" fill="currentColor" stroke="none" />
      <path d="M10.3 3.9 2.6 17.2a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 3.4 13.7 8a.6.6 0 0 0 .3.3l4.6 1.7-4.6 1.7a.6.6 0 0 0-.3.3L12 16.6l-1.7-4.6a.6.6 0 0 0-.3-.3L5.4 10 10 8.3a.6.6 0 0 0 .3-.3Z" />
      <path d="M18.4 15.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8Z" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3.2 8.4 4.2-8.4 4.2L3.6 7.4Z" />
      <path d="m4.2 12 7.8 3.9 7.8-3.9" />
      <path d="m4.2 16.2 7.8 3.9 7.8-3.9" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.2V12l3.2 1.9" />
    </>
  ),
  refresh: (
    <>
      <path d="M20.2 11.4a8.2 8.2 0 1 0-1.3 5.3" />
      <path d="M20.6 4.8v5.2h-5.2" />
    </>
  ),
  trash: (
    <>
      <path d="M4.8 6.8h14.4M9.4 6.8V5.2a1.4 1.4 0 0 1 1.4-1.4h2.4a1.4 1.4 0 0 1 1.4 1.4v1.6" />
      <path d="M6.6 6.8 7.5 19a1.6 1.6 0 0 0 1.6 1.4h5.8a1.6 1.6 0 0 0 1.6-1.4l.9-12.2" />
    </>
  ),
  eye: (
    <>
      <path d="M2.4 12S6 5.6 12 5.6 21.6 12 21.6 12 18 18.4 12 18.4 2.4 12 2.4 12Z" />
      <circle cx="12" cy="12" r="2.9" />
    </>
  ),
  bookmark: <path d="M6.2 3.8h11.6v16.8L12 16.2l-5.8 4.4Z" />,
  branch: (
    <>
      <circle cx="6.4" cy="5.2" r="2.2" />
      <circle cx="6.4" cy="18.8" r="2.2" />
      <circle cx="17.6" cy="9.4" r="2.2" />
      <path d="M6.4 7.4v9.2M6.4 13.6h6.4a4.8 4.8 0 0 0 4.8-4.8" />
    </>
  ),
  page: (
    <>
      <rect x="4.4" y="2.8" width="15.2" height="18.4" rx="1.8" />
      <path d="M8.2 7.4h7.6M8.2 11h7.6M8.2 14.6h4.6" />
    </>
  ),
  arrowRight: <path d="M4.6 12h14m0 0-5.2-5.2M18.6 12l-5.2 5.2" />,
  list: <path d="M8.4 6.4h11.2M8.4 12h11.2M8.4 17.6h11.2M4.4 6.4h.01M4.4 12h.01M4.4 17.6h.01" />,
}

export type IconName = keyof typeof PATHS

export default function Icon({
  name,
  size = 18,
  ...rest
}: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
