/**
 * UserMenu Tests
 * 
 * Feature: user-menu
 * Property 2: Dropdown State Consistency
 * Validates: Requirements 2.1, 2.2, 2.3
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import fc from 'fast-check';
import { UserMenu } from './UserMenu';
import { useAuthStore } from '../stores/authStore';

// Mock the auth store
vi.mock('../stores/authStore', () => ({
  useAuthStore: vi.fn(),
}));

// Mock the auth service
vi.mock('../services/authService', () => ({
  authService: {
    clearAuth: vi.fn(),
  },
}));

const mockUser = {
  id: '1',
  username: 'testuser',
  email: 'test@example.com',
  roles: ['Administrator' as const],
  mfa_enabled: true,
};

const mockLogout = vi.fn().mockResolvedValue(undefined);

const renderUserMenu = () => {
  return render(
    <BrowserRouter>
      <UserMenu />
    </BrowserRouter>
  );
};

describe('UserMenu Properties', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useAuthStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      user: mockUser,
      logout: mockLogout,
      isLoading: false,
    });
  });

  /**
   * Property 2: Dropdown State Consistency
   * For any sequence of toggle operations, isOpen state matches visual
   */
  it('dropdown visibility matches toggle state for any sequence of clicks', () => {
    fc.assert(
      fc.property(
        fc.array(fc.boolean(), { minLength: 1, maxLength: 20 }),
        (clickSequence) => {
          const { unmount } = renderUserMenu();
          
          const button = screen.getByRole('button', { name: /user menu/i });
          let expectedOpen = false;
          
          for (const shouldClick of clickSequence) {
            if (shouldClick) {
              fireEvent.click(button);
              expectedOpen = !expectedOpen;
            }
            
            const dropdown = screen.queryByRole('menu');
            const isVisible = dropdown !== null;
            
            if (isVisible !== expectedOpen) {
              unmount();
              return false;
            }
          }
          
          unmount();
          return true;
        }
      ),
      { numRuns: 50 }
    );
  });

  /**
   * Property: Escape key always closes dropdown
   */
  it('Escape key closes dropdown regardless of how many times it was toggled', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        (toggleCount) => {
          const { unmount } = renderUserMenu();
          
          const button = screen.getByRole('button', { name: /user menu/i });
          
          // Toggle the specified number of times
          for (let i = 0; i < toggleCount; i++) {
            fireEvent.click(button);
          }
          
          // If dropdown is open, Escape should close it
          const dropdownBefore = screen.queryByRole('menu');
          if (dropdownBefore) {
            fireEvent.keyDown(document, { key: 'Escape' });
            const dropdownAfter = screen.queryByRole('menu');
            if (dropdownAfter !== null) {
              unmount();
              return false;
            }
          }
          
          unmount();
          return true;
        }
      ),
      { numRuns: 50 }
    );
  });
});

describe('UserMenu Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useAuthStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      user: mockUser,
      logout: mockLogout,
      isLoading: false,
    });
  });

  it('renders user avatar with correct initials', () => {
    renderUserMenu();
    expect(screen.getByText('TE')).toBeInTheDocument(); // testuser -> TE
  });

  it('displays username on desktop', () => {
    renderUserMenu();
    expect(screen.getByText('testuser')).toBeInTheDocument();
  });

  it('displays role badge', () => {
    renderUserMenu();
    expect(screen.getByText('Administrator')).toBeInTheDocument();
  });

  it('opens dropdown on click', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    
    fireEvent.click(button);
    
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('closes dropdown on Escape key', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    expect(screen.getByRole('menu')).toBeInTheDocument();
    
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('displays Change Password option in dropdown', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    expect(screen.getByText('Change Password')).toBeInTheDocument();
  });

  it('displays Logout option in dropdown', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    expect(screen.getByText('Logout')).toBeInTheDocument();
  });

  it('calls logout when Logout button is clicked', async () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    const logoutButton = screen.getByText('Logout');
    fireEvent.click(logoutButton);
    
    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalled();
    });
  });

  it('displays MFA badge when MFA is enabled', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    expect(screen.getByText('MFA')).toBeInTheDocument();
  });

  it('displays user email in dropdown', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    expect(screen.getByText('test@example.com')).toBeInTheDocument();
  });

  it('has correct ARIA attributes', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    expect(button).toHaveAttribute('aria-haspopup', 'true');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    
    fireEvent.click(button);
    
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu')).toHaveAttribute('aria-labelledby', 'user-menu-button');
  });

  it('handles user without MFA gracefully', () => {
    (useAuthStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      user: { ...mockUser, mfa_enabled: false },
      logout: mockLogout,
      isLoading: false,
    });
    
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    fireEvent.click(button);
    
    expect(screen.queryByText('MFA')).not.toBeInTheDocument();
  });

  it('handles missing user gracefully', () => {
    (useAuthStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      user: null,
      logout: mockLogout,
      isLoading: false,
    });
    
    renderUserMenu();
    
    // Should show fallback "User" and "US" initials (first two letters of "User")
    expect(screen.getByText('User')).toBeInTheDocument();
    expect(screen.getByText('US')).toBeInTheDocument();
  });
});


describe('UserMenu Focus Trap Properties', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useAuthStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      user: mockUser,
      logout: mockLogout,
      isLoading: false,
    });
  });

  /**
   * Property 4: Focus Trap Integrity
   * When dropdown is open, Tab navigation cycles within dropdown elements only
   */
  it('Tab key cycles through menu items when dropdown is open', () => {
    renderUserMenu();
    const button = screen.getByRole('button', { name: /user menu/i });
    
    // Open dropdown
    fireEvent.click(button);
    
    // Get all menu items
    const menuItems = screen.getAllByRole('menuitem');
    expect(menuItems.length).toBeGreaterThan(0);
    
    // First menu item should be focused
    expect(document.activeElement).toBe(menuItems[0]);
    
    // Tab to next item
    fireEvent.keyDown(document, { key: 'Tab' });
    
    // Should still be within menu items (focus trap working)
    const activeElement = document.activeElement;
    const isWithinMenu = menuItems.some(item => item === activeElement || item.contains(activeElement));
    expect(isWithinMenu || activeElement === menuItems[menuItems.length - 1]).toBe(true);
  });

  it('focus stays within dropdown for any number of Tab presses', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 20 }),
        (tabCount) => {
          const { unmount } = renderUserMenu();
          const button = screen.getByRole('button', { name: /user menu/i });
          
          // Open dropdown
          fireEvent.click(button);
          
          const dropdown = screen.queryByRole('menu');
          if (!dropdown) {
            unmount();
            return false;
          }
          
          // Press Tab multiple times
          for (let i = 0; i < tabCount; i++) {
            fireEvent.keyDown(document, { key: 'Tab' });
          }
          
          // Active element should still be within the menu container
          const menuRef = dropdown.closest('div');
          const isWithinMenu = menuRef?.contains(document.activeElement) ?? false;
          
          unmount();
          return isWithinMenu;
        }
      ),
      { numRuns: 30 }
    );
  });
});
