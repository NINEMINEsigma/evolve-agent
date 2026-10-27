import { useLayoutEffect, useRef } from "react";
import { onboardingLabels as labels } from "./labels";

export default function OnboardingPreparing({ onSkip }: { onSkip: () => void }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    buttonRef.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="onboarding-preparing" role="dialog" aria-modal="true" aria-label={labels.preparing}
      onKeyDown={(event) => {
        if (event.key === "Tab") {
          event.preventDefault();
          buttonRef.current?.focus({ preventScroll: true });
        }
      }}>
      <div className="onboarding-preparing-card">
        <h2>{labels.preparing}</h2>
        <p>{labels.preparingHint}</p>
        <button ref={buttonRef} type="button" onClick={onSkip}>{labels.buttons.skip}</button>
      </div>
    </div>
  );
}
