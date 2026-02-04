// ============================================================================
// File: src/hooks/useChatCommands.js
// Purpose: Lightweight dispatcher for Interactive UI actions from AI chat
// ============================================================================

import { useCallback } from 'react';

/**
 * Chat Command Dispatcher Hook
 * Executes structured UI actions returned by the AI assistant
 * 
 * @param {Object} handlers - Map of action type to handler function
 * @returns {Function} dispatchChatAction - Execute a single action
 */
export function useChatCommands(handlers = {}) {
  const dispatchChatAction = useCallback((action) => {
    if (!action || !action.type) {
      console.warn('[ChatCommands] Invalid action:', action);
      return { success: false, error: 'Invalid action format' };
    }

    const handler = handlers[action.type];
    if (!handler) {
      console.warn(`[ChatCommands] No handler for action type: ${action.type}`);
      return { success: false, error: `Unknown action type: ${action.type}` };
    }

    try {
      const result = handler(action.payload || {}, action.meta || {});
      console.log(`[ChatCommands] Executed ${action.type}:`, action.payload);
      return { success: true, result };
    } catch (error) {
      console.error(`[ChatCommands] Error executing ${action.type}:`, error);
      return { success: false, error: error.message };
    }
  }, [handlers]);

  const dispatchChatActions = useCallback((actions) => {
    if (!Array.isArray(actions)) {
      console.warn('[ChatCommands] Expected array of actions, got:', actions);
      return [];
    }

    return actions.map(action => ({
      action,
      ...dispatchChatAction(action)
    }));
  }, [dispatchChatAction]);

  return { dispatchChatAction, dispatchChatActions };
}

/**
 * Supported Action Types (for reference)
 */
export const ChatActionTypes = {
  // Scorecard actions
  SCORECARD_SELECT: 'SCORECARD_SELECT',
  SCORECARD_UPDATE_FIELD: 'SCORECARD_UPDATE_FIELD',
  
  // Scenario actions
  SCENARIO_SET_INPUT: 'SCENARIO_SET_INPUT',
  SCENARIO_RUN: 'SCENARIO_RUN',
  SCENARIO_ADOPT: 'SCENARIO_ADOPT',
  
  // Project actions
  PROJECT_BEGIN: 'PROJECT_BEGIN',
  
  // WBS/Task actions (for Activities page)
  WBS_ADD_TASK: 'WBS_ADD_TASK',
  WBS_UPDATE_TASK: 'WBS_UPDATE_TASK',
  WBS_ADD_DEPENDENCY: 'WBS_ADD_DEPENDENCY',
  
  // View actions
  VIEW_SET: 'VIEW_SET',
  
  // Export actions
  EXPORT: 'EXPORT',
};

/**
 * Parse AI response for UI actions
 * Supports multiple formats: { uiActions }, { actions }, { commands }, { toolCalls }
 */
export function parseUIActions(response) {
  if (!response) return [];
  
  // Try common field names
  const actions = 
    response.uiActions || 
    response.actions || 
    response.commands || 
    response.toolCalls ||
    [];
  
  return Array.isArray(actions) ? actions : [];
}