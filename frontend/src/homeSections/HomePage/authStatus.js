export function readAuthQueryNotice(search) {
  const params = new URLSearchParams(search || '');
  if (params.get('signed_out') === '1') {
    return {
      tone: 'success',
      message: "You've been signed out.",
    };
  }

  if (params.get('verified') === '1') {
    return {
      tone: 'success',
      message: 'Your email is verified. You can continue into Jaspen now.',
    };
  }

  const error = String(params.get('error') || '').trim().toLowerCase();
  switch (error) {
    case 'access_pending':
      return {
        tone: 'info',
        message: "You're on the list. We're reviewing access now.",
        detail: 'Jaspen is opening access carefully so each early user gets the right level of support. We’ll let you in as soon as your spot is confirmed.',
      };
    case 'access_rejected':
      return {
        tone: 'error',
        message: 'We couldn’t confirm access yet.',
      };
    case 'signup_closed':
      return {
        tone: 'info',
        message: 'Jaspen is opening access carefully right now. Use an invite code or request access to join the early list.',
      };
    case 'invite_required':
      return {
        tone: 'info',
        message: 'An invite code is required right now to get into Jaspen.',
      };
    case 'invite_invalid':
      return {
        tone: 'error',
        message: 'That invite code could not be confirmed. Check the code and try again.',
      };
    case 'google_auth_failed':
      return {
        tone: 'error',
        message: 'Google sign-in did not complete. Please try again.',
      };
    case 'google_state_invalid':
      return {
        tone: 'error',
        message: 'Your sign-in session expired before Google returned. Please try again.',
      };
    case 'account_deactivated':
      return {
        tone: 'error',
        message: 'This account is currently unavailable.',
        detail: 'If this looks wrong, contact Jaspen support and we can review the account history and restore access when appropriate.',
      };
    case 'session_expired':
      return {
        tone: 'info',
        message: 'Your session expired. Please sign in again to continue.',
      };
    default:
      return null;
  }
}
