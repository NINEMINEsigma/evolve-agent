import type { SVGProps } from "react";

const common = {
  viewBox: "0 0 16 16",
  width: 16,
  height: 16,
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.4,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

type IconProps = SVGProps<SVGSVGElement>;

export function ChevronIcon({ open = false, ...props }: IconProps & { open?: boolean }) {
  return (
    <svg {...common} {...props}>
      <path d={open ? "M3.5 6l4.5 4 4.5-4" : "M6 3.5l4 4.5-4 4.5"} />
    </svg>
  );
}

export function FolderIcon({ open = false, ...props }: IconProps & { open?: boolean }) {
  return (
    <svg {...common} {...props}>
      <path d={open ? "M1.5 5.5h13l-1.5 7H2.5z" : "M1.5 3.5h5l1.5 2h6.5v7h-13z"} />
    </svg>
  );
}

export function FileIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M3 1.5h6l4 4v9H3z" />
      <path d="M9 1.5v4h4" />
    </svg>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M3 4.5h10M6 4.5v-2h4v2M4.5 4.5l.7 9h5.6l.7-9M6.7 7v4M9.3 7v4" />
    </svg>
  );
}

export function LockIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <rect x="3" y="7" width="10" height="7" rx="1" />
      <path d="M5.5 7V4.8a2.5 2.5 0 015 0V7" />
    </svg>
  );
}

export function ConflictIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M8 1.5l6.5 12H1.5z" />
      <path d="M8 5v4M8 11.5v.1" />
    </svg>
  );
}

export function SyncIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M13 5A5.5 5.5 0 003.2 3.8L2 5M3 11a5.5 5.5 0 009.8 1.2L14 11" />
      <path d="M2 2v3h3M14 14v-3h-3" />
    </svg>
  );
}
