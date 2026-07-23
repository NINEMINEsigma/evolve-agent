import { motion } from "framer-motion";
import "../styles/skeleton.css";

export default function SkeletonScreen() {
  return (
    <motion.div
      className="skeleton-screen"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Header */}
      <div className="skeleton-header">
        <div className="skeleton-header-left">
          <div className="skeleton-item skeleton-icon" />
          <div className="skeleton-item skeleton-badge" />
        </div>
        <div className="skeleton-header-center">
          <div className="skeleton-item skeleton-pill" />
        </div>
        <div className="skeleton-header-right">
          <div className="skeleton-item skeleton-badge" />
          <div className="skeleton-item skeleton-icon" />
        </div>
      </div>

      {/* Sidebar */}
      <div className="skeleton-sidebar">
        <div className="skeleton-sidebar-header">
          <div className="skeleton-item skeleton-search" />
          <div className="skeleton-item skeleton-icon" />
          <div className="skeleton-item skeleton-icon" />
        </div>
        <div className="skeleton-sidebar-list">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton-item skeleton-session" />
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="skeleton-main">
        <div className="skeleton-chat">
          <div className="skeleton-message">
            <div className="skeleton-item skeleton-avatar" />
            <div className="skeleton-item skeleton-bubble" />
          </div>
          <div className="skeleton-message skeleton-message-user">
            <div className="skeleton-item skeleton-avatar" />
            <div className="skeleton-item skeleton-bubble" />
          </div>
          <div className="skeleton-message skeleton-message-long">
            <div className="skeleton-item skeleton-avatar" />
            <div className="skeleton-item skeleton-bubble" />
          </div>
          <div className="skeleton-message">
            <div className="skeleton-item skeleton-avatar" />
            <div className="skeleton-item skeleton-bubble" />
          </div>
        </div>

        {/* Input */}
        <div className="skeleton-input">
          <div className="skeleton-item skeleton-input-btn" />
          <div className="skeleton-item skeleton-input-field" />
          <div className="skeleton-item skeleton-input-btn" />
        </div>
      </div>
    </motion.div>
  );
}