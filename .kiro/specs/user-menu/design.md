# Design Document: User Menu

## Overview

The User Menu feature adds a persistent header component to the application that displays the currently logged-in user's information and provides access to user-related actions. The menu integrates with the existing authentication system (Zustand store) and follows the application's Tailwind CSS design patterns.

## Architecture

The User Menu consists of three main components:

```
┌─────────────────────────────────────────────────────────────────┐
│                        AppHeader                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Logo/Title                              UserMenu        │   │
│  │                                    ┌─────────────────┐   │   │
│  │                                    │ Avatar Username │   │   │
│  │                                    │    ▼ Role      │   │   │
│  │                                    └─────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                              │                   │
│                                    ┌─────────▼─────────┐        │
│                                    │  UserDropdown     │        │
│                                    │ ┌───────────────┐ │        │
│                                    │ │ User Info     │ │        │
│                                    │ │ ─────────────  │ │        │
│                                    │ │ Change Pass   │ │        │
│                                    │ │ ─────────────  │ │        │
│                                    │ │ Logout        │ │        │
│                                    │ └───────────────┘ │        │
│                                    └───────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### Component Hierarchy

1. **AppHeader** - Top-level header component that wraps the entire application
2. **UserMenu** - Trigger button showing avatar and username
3. **UserDropdown** - Dropdown panel with user info and actions

## Components and Interfaces

### UserMenu Component

```typescript
// src/components/UserMenu.tsx

interface UserMenuProps {
  className?: string;
}

interface UserAvatarProps {
  username: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}
```

### AppHeader Component

```typescript
// src/components/AppHeader.tsx

interface AppHeaderProps {
  title?: string;
  showProgress?: boolean;
  currentStep?: number;
  totalSteps?: number;
  children?: React.ReactNode;
}
```

### Integration with Auth Store

The UserMenu component will consume the existing `useAuthStore` hook:

```typescript
// Usage in UserMenu
const { user, logout, isLoading } = useAuthStore();

// User object structure (from existing types/auth.ts)
interface User {
  id: string;
  username: string;
  email?: string;
  role: UserRole;
  mfa_enabled?: boolean;
  require_password_change?: boolean;
  created_at?: string;
  last_login?: string;
}
```

## Data Models

No new data models required. The feature uses the existing `User` type from `types/auth.ts`.

### Role Badge Styling

```typescript
const roleBadgeStyles: Record<UserRole, string> = {
  Administrator: 'bg-purple-100 text-purple-800',
  Operator: 'bg-blue-100 text-blue-800',
  Viewer: 'bg-gray-100 text-gray-800',
};
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Dropdown State Consistency

*For any* sequence of user interactions (clicks, key presses), the dropdown's open/closed state SHALL always match the visual representation—if `isOpen` is true, the dropdown panel is visible; if false, it is hidden.

**Validates: Requirements 2.1, 2.2, 2.3**

### Property 2: Logout Clears All Auth State

*For any* successful logout action, the auth store SHALL have `isAuthenticated: false`, `user: null`, `token: null`, and localStorage SHALL have no auth-related keys.

**Validates: Requirements 3.4, 3.5**

### Property 3: User Display Consistency

*For any* authenticated user, the displayed username and role in the UserMenu SHALL exactly match the `user.username` and `user.role` values from the auth store.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 4: Focus Trap Integrity

*For any* open dropdown state, Tab key navigation SHALL cycle through only the focusable elements within the dropdown panel and not escape to elements outside.

**Validates: Requirements 6.5**

### Property 5: Keyboard Navigation Completeness

*For any* dropdown menu item, it SHALL be reachable and activatable using only keyboard navigation (Tab to focus, Enter to activate).

**Validates: Requirements 6.2**

## Error Handling

### Logout Failure Handling

```typescript
const handleLogout = async () => {
  setIsLoggingOut(true);
  try {
    await logout();
    // Redirect happens in logout action
  } catch (error) {
    // Even on error, clear local state and redirect
    // This ensures user can always "escape" a broken session
    authService.clearAuth();
    navigate('/login');
  } finally {
    setIsLoggingOut(false);
  }
};
```

### Missing User Data

```typescript
// Graceful fallback for missing user data
const displayName = user?.username || 'User';
const displayRole = user?.role || 'Unknown';
const initials = getInitials(displayName); // Returns "U" for unknown
```

## Testing Strategy

### Unit Tests

Unit tests will verify specific component behaviors:

1. **UserAvatar rendering** - Correct initials extraction from usernames
2. **Role badge styling** - Correct CSS classes for each role
3. **Dropdown toggle** - Open/close state management
4. **Keyboard handlers** - Escape key closes dropdown

### Property-Based Tests

Property tests will use `fast-check` to verify universal properties:

1. **Initials extraction** - For any valid username string, initials extraction produces 1-2 uppercase characters
2. **Dropdown state** - For any sequence of toggle operations, final state is predictable
3. **Logout state clearing** - For any user state, logout results in empty auth state

### Test Configuration

- Property tests: minimum 100 iterations
- Test framework: Vitest with React Testing Library
- Property testing library: fast-check

### Example Property Test

```typescript
import fc from 'fast-check';
import { getInitials } from './UserMenu';

describe('UserMenu Properties', () => {
  // Property 1: Initials are always 1-2 uppercase characters
  it('getInitials always returns 1-2 uppercase characters', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        (username) => {
          const initials = getInitials(username);
          return (
            initials.length >= 1 &&
            initials.length <= 2 &&
            initials === initials.toUpperCase()
          );
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

## Implementation Notes

### Integration Points

1. **WizardShell.tsx** - Wrap with AppHeader component
2. **App.tsx** - Add AppHeader to protected routes
3. **authStore.ts** - Use existing logout action

### Responsive Breakpoints

```typescript
// Tailwind responsive classes
const responsiveClasses = {
  // Hide username on mobile, show on md+
  username: 'hidden md:block',
  // Smaller avatar on mobile
  avatar: 'h-8 w-8 md:h-10 md:w-10',
  // Full-width dropdown on mobile
  dropdown: 'w-screen md:w-64 right-0 md:right-auto',
};
```

### Accessibility Attributes

```typescript
// Required ARIA attributes
const ariaAttributes = {
  menuButton: {
    'aria-haspopup': 'true',
    'aria-expanded': isOpen,
    'aria-label': `User menu for ${user?.username}`,
  },
  dropdown: {
    role: 'menu',
    'aria-labelledby': 'user-menu-button',
  },
  menuItem: {
    role: 'menuitem',
    tabIndex: 0,
  },
};
```
