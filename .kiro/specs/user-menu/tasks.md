# Implementation Plan: User Menu

## Overview

This implementation plan creates a User Menu component that displays logged-in user information in the application header and provides access to user actions (logout, change password). The implementation follows the existing React/TypeScript patterns and integrates with the Zustand auth store.

## Tasks

- [x] 1. Create UserAvatar component
  - Create `src/components/UserAvatar.tsx`
  - Implement initials extraction from username
  - Support size variants (sm, md, lg)
  - Apply Tailwind styling with rounded-full background
  - _Requirements: 1.1, 1.4_

- [x] 1.1 Write property test for initials extraction
  - **Property 1: Initials Extraction**
  - For any non-empty username string, getInitials returns 1-2 uppercase characters
  - **Validates: Requirements 1.1**

- [x] 2. Create UserMenu component
  - Create `src/components/UserMenu.tsx`
  - Integrate with useAuthStore to get user data
  - Display UserAvatar and username
  - Display role badge with appropriate styling
  - Implement dropdown toggle state
  - _Requirements: 1.1, 1.2, 1.3, 2.1_

- [x] 3. Create UserDropdown component
  - Create dropdown panel with user info section
  - Add "Change Password" menu item with icon
  - Add "Logout" menu item with icon
  - Add dividers between sections
  - Implement click-outside to close
  - Implement Escape key to close
  - _Requirements: 2.2, 2.3, 2.4, 3.1, 4.1, 5.1, 5.2_

- [x] 3.1 Write property test for dropdown state consistency
  - **Property 2: Dropdown State Consistency**
  - For any sequence of toggle operations, isOpen state matches visual
  - **Validates: Requirements 2.1, 2.2, 2.3**

- [x] 4. Implement logout functionality
  - Wire logout button to authStore.logout()
  - Add loading state during logout
  - Handle logout errors gracefully (still clear local state)
  - Navigate to /login after logout
  - _Requirements: 3.2, 3.3, 3.4, 3.5_

- [x] 4.1 Write property test for logout state clearing
  - **Property 3: Logout Clears Auth State**
  - For any authenticated state, logout results in isAuthenticated=false, user=null, token=null
  - **Validates: Requirements 3.4, 3.5**

- [x] 5. Implement change password navigation
  - Wire "Change Password" button to navigate to /change-password
  - Close dropdown on navigation
  - _Requirements: 4.2, 4.3_

- [x] 6. Add accessibility features
  - Add ARIA attributes (aria-haspopup, aria-expanded, role="menu")
  - Implement keyboard navigation (Tab, Enter)
  - Implement focus trap when dropdown is open
  - _Requirements: 6.2, 6.3, 6.5_

- [x] 6.1 Write property test for focus trap
  - **Property 4: Focus Trap Integrity**
  - When dropdown is open, Tab navigation cycles within dropdown elements only
  - **Validates: Requirements 6.5**

- [x] 7. Add responsive behavior
  - Hide username on mobile (show only avatar)
  - Adjust dropdown positioning for mobile
  - Ensure touch-friendly sizing
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 8. Create AppHeader component
  - Create `src/components/AppHeader.tsx`
  - Include application title/logo
  - Include UserMenu on the right side
  - Apply consistent header styling
  - _Requirements: 1.1, 1.2_

- [x] 9. Integrate AppHeader into application
  - Update WizardShell.tsx to use AppHeader
  - Ensure header appears on all authenticated pages
  - Verify header does not appear on login/public pages
  - _Requirements: 1.1_

- [x] 10. Checkpoint - Ensure all tests pass
  - Run all unit tests
  - Run all property tests
  - Verify manual testing of logout flow
  - Verify manual testing of change password navigation

- [x] 11. Write unit tests for UserMenu component
  - Test avatar renders with correct initials
  - Test role badge displays correct role
  - Test dropdown opens on click
  - Test dropdown closes on Escape
  - Test logout button triggers logout
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3, 3.2_

- [x] 12. Add MFA status indicator (optional enhancement)
  - Display MFA enabled/disabled status in dropdown
  - Show appropriate icon for MFA status
  - _Requirements: 5.3_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required for comprehensive implementation
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The UserMenu integrates with the existing authStore - no backend changes needed
