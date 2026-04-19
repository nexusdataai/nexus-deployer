/**
 * UserAvatar Component
 * Displays user initials in a circular avatar with size variants.
 * 
 * Feature: user-menu
 * Requirements: 1.1, 1.4
 */
import React from 'react';

interface UserAvatarProps {
  username: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

/**
 * Extract initials from a username.
 * Returns 1-2 uppercase characters.
 * 
 * @param username - The username to extract initials from
 * @returns 1-2 uppercase characters representing the user's initials
 */
export function getInitials(username: string): string {
  if (!username || username.trim().length === 0) {
    return 'U';
  }

  const trimmed = username.trim();
  
  // Split by spaces, underscores, dots, or hyphens
  const parts = trimmed.split(/[\s._-]+/).filter(part => part.length > 0);
  
  // Helper to extract first letter character from a string
  const getFirstLetter = (str: string): string => {
    for (const char of str) {
      if (/[a-zA-Z]/.test(char)) {
        return char.toUpperCase();
      }
    }
    return '';
  };
  
  if (parts.length === 0) {
    // If no valid parts, try to find any letter in the original string
    const letter = getFirstLetter(trimmed);
    return letter || 'U';
  }
  
  if (parts.length === 1) {
    const word = parts[0];
    // Get first two letters from the word
    const letters: string[] = [];
    for (const char of word) {
      if (/[a-zA-Z]/.test(char)) {
        letters.push(char.toUpperCase());
        if (letters.length >= 2) break;
      }
    }
    return letters.length > 0 ? letters.join('') : 'U';
  }
  
  // Multiple words: take first letter of first two words
  const first = getFirstLetter(parts[0]);
  const second = getFirstLetter(parts[1]);
  
  if (first && second) {
    return first + second;
  } else if (first) {
    return first;
  }
  
  return 'U';
}

const sizeClasses = {
  sm: 'h-8 w-8 text-sm',
  md: 'h-10 w-10 text-base',
  lg: 'h-12 w-12 text-lg',
};

export const UserAvatar: React.FC<UserAvatarProps> = ({
  username,
  size = 'md',
  className = '',
}) => {
  const initials = getInitials(username);
  
  return (
    <div
      className={`
        inline-flex items-center justify-center
        rounded-full bg-blue-600 text-white font-medium
        ${sizeClasses[size]}
        ${className}
      `}
      aria-label={`Avatar for ${username || 'User'}`}
    >
      {initials}
    </div>
  );
};

export default UserAvatar;
