import React, { useState } from 'react';
import ChatPane from '../../common/ChatPane/ChatPane'; // ✅ CORRECTED PATH
import styles from './Layout.module.css';

const Layout = ({ 
  title, 
  onSave, 
  onDownload, 
  children, 
  chatConfig = null,
  currentData = {},
  onDataUpdate = () => {},
  completionPercentage = 0,
  layoutType = 'default' // NEW: Add layout type prop
}) => {
  const [isChatVisible, setIsChatVisible] = useState(true);

  // SIPOC-specific layout
  if (layoutType === 'sipoc') {
    return (
      <div className={styles.layoutContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>{title}</h1>
            {completionPercentage > 0 && (
              <div className={styles.progressSection}>
                <div className={styles.progressBar}>
                  <div 
                    className={styles.progressFill} 
                    style={{ width: `${completionPercentage}%` }}
                  ></div>
                </div>
                <span className={styles.progressText}>{completionPercentage}% Complete</span>
              </div>
            )}
          </div>
          <div className={styles.headerActions}>
            {chatConfig && (
              <button 
                className={styles.chatToggleBtn}
                onClick={() => setIsChatVisible(!isChatVisible)}
              >
                <i className={`fas ${isChatVisible ? 'fa-eye-slash' : 'fa-eye'}`}></i>
                {isChatVisible ? 'Hide' : 'Show'} AI Guide
              </button>
            )}
            {onSave && (
              <button className={styles.saveBtn} onClick={onSave}>
                <i className="fas fa-save"></i> Save Draft
              </button>
            )}
            {onDownload && (
              <button className={styles.exportBtn} onClick={onDownload}>
                <i className="fas fa-download"></i> Export PDF
              </button>
            )}
          </div>
        </div>

        {/* SIPOC-specific Main Content */}
        <div className={styles.sipocMainContent}>
          {/* Top Section: Process Info + Chat */}
          <div className={styles.sipocTopSection}>
            <div className={styles.sipocProcessInfo}>
              {/* This will contain the process information form */}
              {children?.processInfo}
            </div>
            
            {/* AI Chat Panel - Always visible on the right */}
            {chatConfig && isChatVisible && (
              <div className={styles.sipocChatArea}>
                <ChatPane 
                  toolConfig={chatConfig}
                  currentData={currentData}
                  onDataUpdate={onDataUpdate}
                />
              </div>
            )}
          </div>

          {/* Full Width SIPOC Grid Section */}
          <div className={styles.sipocGridSection}>
            {children?.sipocGrid}
          </div>

          {/* Bottom Section: Process Flow */}
          <div className={styles.sipocBottomSection}>
            {children?.processFlow}
          </div>
        </div>
      </div>
    );
  }

  // Default layout (unchanged)
  return (
    <div className={styles.layoutContainer}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <h1>{title}</h1>
          {completionPercentage > 0 && (
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div 
                  className={styles.progressFill} 
                  style={{ width: `${completionPercentage}%` }}
                ></div>
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          )}
        </div>
        <div className={styles.headerActions}>
          {chatConfig && (
            <button 
              className={styles.chatToggleBtn}
              onClick={() => setIsChatVisible(!isChatVisible)}
            >
              <i className={`fas ${isChatVisible ? 'fa-eye-slash' : 'fa-eye'}`}></i>
              {isChatVisible ? 'Hide' : 'Show'} AI Guide
            </button>
          )}
          {onSave && (
            <button className={styles.saveBtn} onClick={onSave}>
              <i className="fas fa-save"></i> Save Draft
            </button>
          )}
          {onDownload && (
            <button className={styles.exportBtn} onClick={onDownload}>
              <i className="fas fa-download"></i> Export PDF
            </button>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className={styles.mainContent}>
        <div className={`${styles.contentArea} ${chatConfig && isChatVisible ? styles.withChat : styles.fullWidth}`}>
          {children}
        </div>
        
        {/* AI Chat Panel */}
        {chatConfig && isChatVisible && (
          <div className={styles.chatArea}>
            <ChatPane 
              toolConfig={chatConfig}
              currentData={currentData}
              onDataUpdate={onDataUpdate}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default Layout;

