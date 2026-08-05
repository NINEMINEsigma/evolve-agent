import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import "../styles/splash.css";
import { TIMING } from "../constants/timing";

interface SplashScreenProps {
  onFinish: () => void;
}

export default function SplashScreen({ onFinish }: SplashScreenProps) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const minTimer = setTimeout(() => {
      setExiting(true);
      setTimeout(onFinish, TIMING.SPLASH_FADE_DELAY);
    }, TIMING.SPLASH_MIN_DISPLAY);

    const maxTimer = setTimeout(() => {
      setExiting(true);
      setTimeout(onFinish, TIMING.SPLASH_FADE_DELAY);
    }, TIMING.SPLASH_MAX_DISPLAY);

    return () => {
      clearTimeout(minTimer);
      clearTimeout(maxTimer);
    };
  }, [onFinish]);

  const handleSkip = () => {
    if (exiting) return;
    setExiting(true);
    setTimeout(onFinish, TIMING.SPLASH_FADE_DELAY);
  };

  return (
    <AnimatePresence>
      {!exiting && (
        <motion.div
          className="splash-screen"
          onClick={handleSkip}
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, filter: "blur(12px)" }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="splash-bg" />
          <div className="splash-content">
            <div className="splash-logo">Evolve Agent</div>
            <div className="splash-tagline">Self-Evolving AI</div>
            <div className="splash-loader">
              <div className="splash-loader-bar" />
            </div>
          </div>
          <div className="splash-skip">Click to skip</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}