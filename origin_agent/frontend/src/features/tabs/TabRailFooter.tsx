import type { ReactNode } from "react";

export interface TabRailFooterProps {
  commandMenu: ReactNode;
}

export default function TabRailFooter({ commandMenu }: TabRailFooterProps) {
  return (
    <div className="tab-rail-footer" data-tour="tab-rail-footer">
      {commandMenu}
    </div>
  );
}
