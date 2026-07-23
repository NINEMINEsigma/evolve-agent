import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import "../styles/splash.css";

interface SplashScreenProps {
  onFinish: () => void;
}

const MIN_DISPLAY_TIME = 800;
const MAX_DISPLAY_TIME = 3000;

export default function SplashScreen({ onFinish }: SplashScreenProps) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const minTimer = setTimeout(() => {
      setExiting(true);
      setTimeout(onFinish, 500);
    }, MIN_DISPLAY_TIME);

    const maxTimer = setTimeout(() => {
      setExiting(true);
      setTimeout(onFinish, 500);
    }, MAX_DISPLAY_TIME);

    return () => {
      clearTimeout(minTimer);
      clearTimeout(maxTimer);
    };
  }, [onFinish]);

  const handleSkip = () => {
    if (exiting) return;
    setExiting(true);
    setTimeout(onFinish, 500);
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