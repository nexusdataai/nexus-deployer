"""
Resource Resolver
Resolves paths to bundled resources across different runtime environments.

Supports:
- Electron packaged app (resources/templates/)
- PyInstaller bundle (_MEIPASS/deploy/templates/)
- Development mode (deploy/templates/ relative to project)
"""
import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List


logger = logging.getLogger(__name__)


class TemplateNotFoundError(Exception):
    """Raised when a template file cannot be found."""
    
    def __init__(self, template_name: str, searched_paths: List[str]):
        self.template_name = template_name
        self.searched_paths = searched_paths
        self.remediation = self._get_remediation()
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        return (
            f"Template '{self.template_name}' not found.\n"
            f"Searched locations:\n"
            + "\n".join(f"  - {p}" for p in self.searched_paths)
            + f"\n\nRemediation: {self.remediation}"
        )
    
    def _get_remediation(self) -> str:
        if ResourceResolver.is_packaged():
            return "Please reinstall the application to restore missing templates."
        return "Ensure the deploy/templates directory exists and contains all required templates."


class ResourceResolver:
    """Resolves paths to bundled resources across different runtime environments."""
    
    # Template mapping from stack type to relative path
    TEMPLATE_MAP = {
        "frontend-global": "frontend/global-stack.yaml",
        "frontend-cognito": "frontend/cognito-stack.yaml",
        "frontend-regional": "frontend/regional-stack.yaml",
        "backend-foundation": "backend/foundation-stack.yaml",
        "backend-iam-roles": "backend/iam-roles-stack.yaml",
        "backend-regional-cert": "backend/regional-cert-stack.yaml",
        "backend-storage": "backend/storage-stack.yaml",
        "backend-network": "backend/network-stack.yaml",
        "backend-service": "backend/service-stack.yaml",
        "backend-domain": "backend/domain-stack.yaml",
    }
    
    @staticmethod
    def is_packaged() -> bool:
        """
        Check if running in a packaged environment.
        
        Returns:
            True if running in Electron packaged app or PyInstaller bundle
        """
        # Check for Electron packaged mode
        if os.environ.get('ELECTRON_RESOURCES_PATH'):
            return True
        
        # Check for PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return True
        
        return False
    
    @staticmethod
    def is_electron() -> bool:
        """Check if running in Electron environment."""
        return bool(os.environ.get('ELECTRON_RESOURCES_PATH'))
    
    @staticmethod
    def is_pyinstaller() -> bool:
        """Check if running as PyInstaller bundle."""
        return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
    
    @staticmethod
    def get_environment_info() -> Dict[str, Any]:
        """
        Get information about the current runtime environment.
        
        Returns:
            Dict with environment details including type, paths, and detection info
        """
        info = {
            'is_packaged': ResourceResolver.is_packaged(),
            'is_electron': ResourceResolver.is_electron(),
            'is_pyinstaller': ResourceResolver.is_pyinstaller(),
            'environment_type': 'development',
            'templates_dir': None,
            'electron_resources_path': os.environ.get('ELECTRON_RESOURCES_PATH'),
            'pyinstaller_meipass': getattr(sys, '_MEIPASS', None),
            'cwd': str(Path.cwd()),
        }
        
        if info['is_electron']:
            info['environment_type'] = 'electron_packaged'
        elif info['is_pyinstaller']:
            info['environment_type'] = 'pyinstaller_bundle'
        
        try:
            templates_dir = ResourceResolver.get_templates_dir()
            info['templates_dir'] = str(templates_dir)
            info['templates_dir_exists'] = templates_dir.exists()
        except Exception as e:
            info['templates_dir_error'] = str(e)
        
        return info
    
    @staticmethod
    def get_templates_dir() -> Path:
        """
        Get the templates directory based on runtime environment.
        
        Priority order:
        1. Electron packaged app (ELECTRON_RESOURCES_PATH/templates)
        2. PyInstaller bundle (sys._MEIPASS/deploy/templates)
        3. Development mode (relative to this file: ../../deploy/templates)
        4. Current working directory fallback (deploy/templates)
        
        Returns:
            Path to the templates directory
        """
        searched_paths = []
        
        # 1. Check for Electron packaged mode
        electron_resources = os.environ.get('ELECTRON_RESOURCES_PATH')
        if electron_resources:
            electron_path = Path(electron_resources) / "templates"
            searched_paths.append(str(electron_path))
            if electron_path.exists():
                logger.debug(f"Using Electron templates path: {electron_path}")
                return electron_path
        
        # 2. Check for PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            meipass_path = Path(sys._MEIPASS) / "deploy" / "templates"
            searched_paths.append(str(meipass_path))
            if meipass_path.exists():
                logger.debug(f"Using PyInstaller templates path: {meipass_path}")
                return meipass_path
        
        # 3. Development mode - relative to this file
        # This file is at: backend/app/utils/resource_resolver.py
        # Templates are at: deploy/templates
        dev_path = Path(__file__).parent.parent.parent.parent / "deploy" / "templates"
        searched_paths.append(str(dev_path))
        if dev_path.exists():
            logger.debug(f"Using development templates path: {dev_path}")
            return dev_path
        
        # 4. Fallback - current working directory
        cwd_path = Path.cwd() / "deploy" / "templates"
        searched_paths.append(str(cwd_path))
        if cwd_path.exists():
            logger.debug(f"Using CWD templates path: {cwd_path}")
            return cwd_path
        
        # Log warning but return the dev path (will fail with clear error later)
        logger.warning(
            f"Templates directory not found. Searched: {searched_paths}. "
            f"Returning dev path for clearer error messages."
        )
        return dev_path
    
    @staticmethod
    def get_template_path(template_name: str) -> Path:
        """
        Get absolute path to a specific template file.
        
        Args:
            template_name: Either a stack type (e.g., 'backend-foundation') 
                          or a relative path (e.g., 'backend/foundation-stack.yaml')
        
        Returns:
            Absolute path to the template file
            
        Raises:
            TemplateNotFoundError: If template doesn't exist at resolved path
        """
        templates_dir = ResourceResolver.get_templates_dir()
        
        # Check if it's a stack type that needs mapping
        if template_name in ResourceResolver.TEMPLATE_MAP:
            relative_path = ResourceResolver.TEMPLATE_MAP[template_name]
        else:
            relative_path = template_name
        
        template_path = templates_dir / relative_path
        absolute_path = template_path.resolve()
        
        if not absolute_path.exists():
            searched_paths = [str(absolute_path)]
            raise TemplateNotFoundError(template_name, searched_paths)
        
        return absolute_path
    
    @staticmethod
    def get_all_template_paths() -> Dict[str, Path]:
        """
        Get paths to all known templates.
        
        Returns:
            Dict mapping stack type to absolute template path
        """
        templates_dir = ResourceResolver.get_templates_dir()
        result = {}
        
        for stack_type, relative_path in ResourceResolver.TEMPLATE_MAP.items():
            template_path = templates_dir / relative_path
            if template_path.exists():
                result[stack_type] = template_path.resolve()
        
        return result
    
    @staticmethod
    def get_manifest_path() -> Path:
        """
        Get path to the template manifest file.
        
        Returns:
            Path to template-manifest.json
        """
        templates_dir = ResourceResolver.get_templates_dir()
        return templates_dir / "template-manifest.json"
