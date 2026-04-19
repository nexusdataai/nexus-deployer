#!/usr/bin/env python3
"""
Safe emoji replacement script - replaces emoji characters with ASCII equivalents.
This script processes files line by line to avoid corruption.
"""
import os
import re

# Emoji to ASCII mapping
EMOJI_MAP = {
    # Status indicators
    '✅': '[OK]',
    '❌': '[X]',
    '✓': '[OK]',
    '⚠': '[!]',
    '⏳': '[...]',
    'ℹ': '[i]',
    '⚡': '[!]',
    '🎉': '[OK]',
    '💡': '[i]',
    '🔥': '[!]',
    '⭐': '[*]',
    # Actions
    '🔄': '[SYNC]',
    '🧹': '[CLEAN]',
    '📌': '[PIN]',
    '📝': '[NOTE]',
    '📦': '[PKG]',
    '🔧': '[TOOL]',
    '🔐': '[LOCK]',
    '📊': '[CHART]',
    '📋': '[LIST]',
    '🔑': '[KEY]',
    '🔗': '[LINK]',
    '🔍': '[DBG]',
    '📧': '[EMAIL]',
    '🔒': '[SECURE]',
    '🚀': '[LAUNCH]',
    '🏗': '[BUILD]',
    '🐳': '[DOCKER]',
    '📍': '[LOC]',
    '🏷': '[TAG]',
    '🌐': '[WEB]',
    '🪣': '[BUCKET]',
    # File/folder
    '📁': '[DIR]',
    '📂': '[DIR]',
    '🗑': '[DEL]',
    '💾': '[SAVE]',
    '🔀': '[MERGE]',
    # Arrows
    '➡': '->',
    '⬅': '<-',
    '⬆': '^',
    '⬇': 'v',
    '→': '->',
    '←': '<-',
    '↻': '[REFRESH]',
    # Other
    '•': '*',
    '○': 'o',
    '▶': '>',
    '🆕': '[NEW]',
    '🆔': '[ID]',
}

def replace_emojis_in_line(line):
    """Replace emojis in a single line."""
    result = line
    for emoji, replacement in EMOJI_MAP.items():
        result = result.replace(emoji, replacement)
    return result

def process_file(filepath):
    """Process a single file, replacing emojis."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        modified = False
        new_lines = []
        for line in lines:
            new_line = replace_emojis_in_line(line)
            if new_line != line:
                modified = True
            new_lines.append(new_line)
        
        if modified:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    """Process all Python files in the app directory."""
    modified_files = []
    
    for root, dirs, files in os.walk('app'):
        # Skip __pycache__ and venv
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'venv', '.git')]
        
        for filename in files:
            if filename.endswith('.py'):
                filepath = os.path.join(root, filename)
                if process_file(filepath):
                    modified_files.append(filepath)
                    print(f"Fixed: {filepath}")
    
    print(f"\nModified {len(modified_files)} files.")
    return modified_files

if __name__ == '__main__':
    main()
