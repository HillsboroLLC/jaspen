import React, { useState } from 'react';
// --- CORRECTED IMPORT PATH ---
import { useAuth } from '../../All/shared/auth/AuthContext';
import styles from './RoleSwitcher.module.css';

const RoleSwitcher = () => {
  const { 
    user, 
    currentUserRole, 
    setUserRole, 
    USER_ROLES,
    isAdmin,
    isProjectLead,
    isTeamMember
  } = useAuth();
  
  const [isOpen, setIsOpen] = useState(false);

  const handleRoleChange = (newRole) => {
    if (user && newRole !== currentUserRole) {
      setUserRole(user.id, newRole);
      setIsOpen(false);
      // Refresh the page to see changes
      window.location.reload();
    }
  };

  const getRoleDisplayName = (role) => {
    switch (role) {
      case USER_ROLES.ADMIN:
        return 'Admin';
      case USER_ROLES.PROJECT_LEAD:
        return 'Project Lead';
      case USER_ROLES.TEAM_MEMBER:
        return 'Team Member';
      default:
        return 'Unknown';
    }
  };

  const getRoleIcon = (role) => {
    switch (role) {
      case USER_ROLES.ADMIN:
        return 'fas fa-crown';
      case USER_ROLES.PROJECT_LEAD:
        return 'fas fa-user-tie';
      case USER_ROLES.TEAM_MEMBER:
        return 'fas fa-user';
      default:
        return 'fas fa-question';
    }
  };

  if (!user) return null;

  return (
    <div className={styles.roleSwitcher}>
      <div 
        className={styles.roleDropdownTrigger}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className={styles.roleLabel}>Role:</span>
        <div className={styles.currentRole}>
          <i className={getRoleIcon(currentUserRole)}></i>
          <span>{getRoleDisplayName(currentUserRole)}</span>
          <i className={`fas fa-chevron-${isOpen ? 'up' : 'down'} ${styles.chevron}`}></i>
        </div>
      </div>

      {isOpen && (
        <>
          <div className={styles.dropdownOverlay} onClick={() => setIsOpen(false)} />
          <div className={styles.roleDropdown}>
            {Object.values(USER_ROLES).map((role) => (
              <button
                key={role}
                className={`${styles.roleOption} ${currentUserRole === role ? styles.active : ''}`}
                onClick={() => handleRoleChange(role)}
              >
                <i className={getRoleIcon(role)}></i>
                <span>{getRoleDisplayName(role)}</span>
                {currentUserRole === role && (
                  <i className="fas fa-check"></i>
                )}
              </button>
            ))}
            <div className={styles.testingNote}>
              <i className="fas fa-flask"></i>
              <span>Testing Mode</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default RoleSwitcher;

